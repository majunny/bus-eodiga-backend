"""BUS어디가 Render용 FastAPI 진입점."""

from secrets import compare_digest
from typing import Optional
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import AuthenticatedUser, get_current_user
from backend.bus_stops import BusStopService, get_bus_stop_service
from backend.config import BackendSettings, get_settings
from backend.firebase import initialize_firestore
from backend.models import (
    FindNearestRouteRequest,
    FindNearestRouteResponse,
    BusStopResponse,
    HealthResponse,
    ModiKioskRideRequestCreate,
    RequestSource,
    RideRequestCreate,
    RideRequestRecord,
    RideStatus,
    PlaceSearchResponse,
    VehicleProgressRequest,
    VehicleTripPollResponse,
    VehicleTripResponse,
)
from backend.place_search import NominatimPlaceSearchService, PlaceSearchError, PlaceSearchService
from backend.modi_stops import MODI_DEPOT_STOP_ID, MODI_STOPS_BY_ID, modi_place
from backend.repository import FirestoreRideRepository, MemoryRideRepository, RideRepository
from backend.routing import OsrmRoutingService, RoutingService, RoutingServiceError
from backend.simulation import run_demo_trip_simulation


def require_vehicle_api_key(
    request: Request,
    vehicle_api_key: str = Header(default="", alias="X-Vehicle-Key"),
) -> None:
    """하드웨어 차량 API를 활성화하고 공유 비밀키가 일치하는지 확인한다."""

    settings: BackendSettings = request.app.state.settings
    if not settings.hardware_vehicle_control_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hardware vehicle control is disabled")
    if not settings.vehicle_api_key or not compare_digest(vehicle_api_key, settings.vehicle_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid vehicle API key")


def require_modi_kiosk_api_key(
    request: Request,
    kiosk_api_key: str = Header(default="", alias="X-Kiosk-Key"),
) -> None:
    """동부아파트 MODI 키오스크 전용 공유키를 검증한다."""

    settings: BackendSettings = request.app.state.settings
    if not settings.modi_kiosk_api_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MODI kiosk API is disabled")
    if not settings.modi_kiosk_api_key or not compare_digest(kiosk_api_key, settings.modi_kiosk_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid kiosk API key")


def create_app(
    settings: Optional[BackendSettings] = None,
    repository: Optional[RideRepository] = None,
    routing_service: Optional[RoutingService] = None,
    bus_stop_service: Optional[BusStopService] = None,
    place_search_service: Optional[PlaceSearchService] = None,
) -> FastAPI:
    """설정과 저장소를 주입할 수 있는 FastAPI 앱을 생성한다."""

    active_settings = settings or get_settings()
    if repository is None:
        if active_settings.store_backend.lower() == "firestore":
            repository = FirestoreRideRepository(initialize_firestore(active_settings))
        else:
            repository = MemoryRideRepository()

    application = FastAPI(title=active_settings.app_name, version="0.1.0")
    application.state.settings = active_settings
    application.state.ride_repository = repository
    application.state.routing_service = routing_service or OsrmRoutingService(
        base_url=active_settings.osrm_base_url,
        timeout_seconds=active_settings.routing_timeout_seconds,
    )
    application.state.bus_stop_service = bus_stop_service or get_bus_stop_service()
    application.state.place_search_service = place_search_service or NominatimPlaceSearchService(
        base_url=active_settings.nominatim_base_url,
        timeout_seconds=active_settings.place_search_timeout_seconds,
    )

    if active_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=active_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Vehicle-Key", "X-Kiosk-Key"],
        )

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        """Render가 배포 상태를 확인할 공개 엔드포인트."""

        current: BackendSettings = request.app.state.settings
        return HealthResponse(status="ok", environment=current.environment, store_backend=current.store_backend)

    @application.post("/api/find_nearest", response_model=FindNearestRouteResponse)
    def find_nearest_route(
        payload: FindNearestRouteRequest,
        request: Request,
    ) -> FindNearestRouteResponse:
        """Android에 가장 가까운 목적지까지의 OSM 도로 경로를 반환한다."""

        service: RoutingService = request.app.state.routing_service
        try:
            return service.find_nearest(payload)
        except RoutingServiceError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

    @application.get("/v1/bus-stops", response_model=list[BusStopResponse])
    def search_bus_stops(
        request: Request,
        query: str = Query(default="", max_length=100),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[BusStopResponse]:
        """정류장 이름으로 울산 정류소를 검색한다."""

        service: BusStopService = request.app.state.bus_stop_service
        return service.search(query=query, limit=limit)

    @application.get("/v1/bus-stops/nearby", response_model=list[BusStopResponse])
    def nearby_bus_stops(
        request: Request,
        latitude: float = Query(ge=-90.0, le=90.0),
        longitude: float = Query(ge=-180.0, le=180.0),
        radius_m: float = Query(default=2_000.0, ge=50.0, le=20_000.0),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[BusStopResponse]:
        """현재 위치 주변 정류소를 거리순으로 반환한다."""

        service: BusStopService = request.app.state.bus_stop_service
        return service.nearby(latitude, longitude, radius_m, limit)

    @application.get("/v1/places/search", response_model=list[PlaceSearchResponse])
    def search_places(
        request: Request,
        query: str = Query(min_length=2, max_length=100),
        limit: int = Query(default=10, ge=1, le=10),
    ) -> list[PlaceSearchResponse]:
        """도착지 이름으로 울산 영역의 OSM 장소를 검색한다."""

        service: PlaceSearchService = request.app.state.place_search_service
        try:
            return service.search(query=query, limit=limit)
        except PlaceSearchError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

    @application.post(
        "/v1/ride-requests",
        response_model=RideRequestRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def create_ride_request(
        payload: RideRequestCreate,
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ) -> RideRequestRecord:
        """인증 사용자 소유의 호출을 중복 없이 생성한다."""

        store: RideRepository = request.app.state.ride_repository
        record = RideRequestRecord.new(str(uuid4()), user.uid, payload)
        return store.create(record, idempotency_key)

    @application.post(
        "/v1/modi-kiosk/ride-requests",
        response_model=RideRequestRecord,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_modi_kiosk_api_key)],
    )
    def create_modi_kiosk_ride_request(
        payload: ModiKioskRideRequestCreate,
        request: Request,
        background_tasks: BackgroundTasks,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ) -> RideRequestRecord:
        """동부아파트 키오스크 호출을 만들고 Android와 같은 공동 배차열에 참여시킨다."""

        try:
            pickup = modi_place(MODI_DEPOT_STOP_ID)
            destination = modi_place(payload.destination_place_id)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Destination is not one of the six MODI stops",
            ) from error
        if destination.place_id == pickup.place_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Destination must differ from the Dongbu depot stop",
            )

        current: BackendSettings = request.app.state.settings
        if not current.enable_demo_dispatch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo dispatch is disabled")
        store: RideRepository = request.app.state.ride_repository
        request_id = str(uuid4())
        user_id = f"modi-kiosk:{payload.device_id}:{request_id}"
        record = RideRequestRecord.new(
            request_id,
            user_id,
            RideRequestCreate(
                source=RequestSource.MODI_KIOSK,
                pickup=pickup,
                destination=destination,
                passenger_count=payload.passenger_count,
                mobility_support=payload.mobility_support,
                guardian_notification_enabled=False,
            ),
        )
        saved = store.create(record, idempotency_key)
        pooled = store.join_demo_pool(
            saved.request_id,
            saved.user_id,
            "modi-bus-01",
            2,
            current.demo_queue_ttl_seconds,
            2,
        )
        if pooled is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Kiosk request could not join dispatch")
        # MODI 운행은 실제 차량 브리지가 선점·보고한다. 일반 시연만 자동 운행한다.
        if current.demo_auto_simulation and not current.hardware_vehicle_control_enabled and pooled.demo_trip_id and pooled.source not in {RequestSource.MODI_APP, RequestSource.MODI_KIOSK}:
            background_tasks.add_task(
                run_demo_trip_simulation,
                store,
                pooled.demo_trip_id,
                current.demo_travel_seconds,
                current.demo_dwell_seconds,
            )
        return pooled

    @application.get("/v1/ride-requests/{request_id}", response_model=RideRequestRecord)
    def get_ride_request(
        request_id: str,
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> RideRequestRecord:
        """본인의 호출만 조회한다."""

        store: RideRepository = request.app.state.ride_repository
        record = store.get(request_id)
        if record is None or record.user_id != user.uid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride request not found")
        return record

    @application.post("/v1/ride-requests/{request_id}/cancel", response_model=RideRequestRecord)
    def cancel_ride_request(
        request_id: str,
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> RideRequestRecord:
        """본인의 호출을 취소한다."""

        store: RideRepository = request.app.state.ride_repository
        record = store.cancel(request_id, user.uid)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride request not found")
        return record

    @application.post("/v1/ride-requests/{request_id}/demo-assign", response_model=RideRequestRecord)
    def assign_demo_vehicle(
        request_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> RideRequestRecord:
        """대회 시연에서 Firestore 배차 이벤트를 실제로 발생시킨다."""

        current: BackendSettings = request.app.state.settings
        if not current.enable_demo_dispatch:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo dispatch is disabled")
        store: RideRepository = request.app.state.ride_repository
        existing = store.get(request_id)
        if existing is None or existing.user_id != user.uid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride request not found")
        is_modi_request = existing.source in {RequestSource.MODI_APP, RequestSource.MODI_KIOSK}
        if is_modi_request:
            place_ids = {existing.pickup.place_id, existing.destination.place_id}
            if not place_ids.issubset(MODI_STOPS_BY_ID):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="MODI requests may use only the six model stops",
                )
        vehicle_id = "modi-bus-01" if is_modi_request else "demo-bus-01"
        dispatch_group_size = 2 if is_modi_request else current.demo_group_size
        record = store.join_demo_pool(
            request_id,
            user.uid,
            vehicle_id,
            dispatch_group_size,
            current.demo_queue_ttl_seconds,
            2,
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride request not found")
        if current.demo_auto_simulation and not current.hardware_vehicle_control_enabled and record.demo_trip_id and record.source not in {RequestSource.MODI_APP, RequestSource.MODI_KIOSK}:
            background_tasks.add_task(
                run_demo_trip_simulation,
                store,
                record.demo_trip_id,
                current.demo_travel_seconds,
                current.demo_dwell_seconds,
            )
        return record

    @application.get(
        "/v1/vehicles/{vehicle_id}/trips/next",
        response_model=VehicleTripPollResponse,
        dependencies=[Depends(require_vehicle_api_key)],
    )
    def poll_vehicle_trip(vehicle_id: str, request: Request) -> VehicleTripPollResponse:
        """MODI 차량이 아직 선점되지 않은 다음 공동 운행을 조회한다."""

        store: RideRepository = request.app.state.ride_repository
        trip = store.find_available_demo_trip(vehicle_id)
        return VehicleTripPollResponse(
            trip=VehicleTripResponse.model_validate(trip) if trip is not None else None,
        )

    @application.post(
        "/v1/vehicles/{vehicle_id}/trips/{trip_id}/claim",
        response_model=VehicleTripResponse,
        dependencies=[Depends(require_vehicle_api_key)],
    )
    def claim_vehicle_trip(vehicle_id: str, trip_id: str, request: Request) -> VehicleTripResponse:
        """한 MODI 차량만 운행을 실행하도록 원자적으로 선점한다."""

        store: RideRepository = request.app.state.ride_repository
        existing = store.get_demo_trip(trip_id)
        if existing is None or existing.get("vehicle_id") != vehicle_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle trip not found")
        claimed = store.claim_demo_trip_simulation(trip_id)
        if claimed is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle trip is already claimed")
        return VehicleTripResponse.model_validate(claimed)

    @application.post(
        "/v1/vehicles/{vehicle_id}/trips/{trip_id}/progress",
        response_model=VehicleTripResponse,
        dependencies=[Depends(require_vehicle_api_key)],
    )
    def report_vehicle_progress(
        vehicle_id: str,
        trip_id: str,
        payload: VehicleProgressRequest,
        request: Request,
    ) -> VehicleTripResponse:
        """MODI 차량의 출발·도착·승하차 상태를 Android와 Firestore에 반영한다."""

        store: RideRepository = request.app.state.ride_repository
        trip = store.get_demo_trip(trip_id)
        if trip is None or trip.get("vehicle_id") != vehicle_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle trip not found")
        if not trip.get("simulation_started"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle trip is not claimed")
        steps = list(trip.get("route_steps") or [])
        if payload.stop_index >= len(steps):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid route stop index")

        step = steps[payload.stop_index]
        request_id = None
        request_status = None
        if payload.phase == "BOARDED":
            if step.get("type") != "PICKUP":
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="BOARDED requires a pickup stop")
            request_id = str(step.get("request_id"))
            request_status = RideStatus.PICKED_UP
        elif payload.phase == "DROPPED_OFF":
            if step.get("type") != "DROPOFF":
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="DROPPED_OFF requires a dropoff stop")
            request_id = str(step.get("request_id"))
            request_status = RideStatus.COMPLETED
        elif payload.phase == "COMPLETED" and payload.stop_index != len(steps) - 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="COMPLETED requires the final stop")

        store.update_demo_trip_progress(
            trip_id,
            payload.stop_index,
            payload.phase,
            request_id=request_id,
            request_status=request_status,
        )
        updated = store.get_demo_trip(trip_id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle trip not found")
        return VehicleTripResponse.model_validate(updated)

    return application


app = create_app()
