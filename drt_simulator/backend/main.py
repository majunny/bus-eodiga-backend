"""BUS어디가 Render용 FastAPI 진입점."""

from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import AuthenticatedUser, get_current_user
from backend.config import BackendSettings, get_settings
from backend.firebase import initialize_firestore
from backend.models import HealthResponse, RideRequestCreate, RideRequestRecord
from backend.repository import FirestoreRideRepository, MemoryRideRepository, RideRepository


def create_app(
    settings: Optional[BackendSettings] = None,
    repository: Optional[RideRepository] = None,
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

    if active_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=active_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        """Render가 배포 상태를 확인할 공개 엔드포인트."""

        current: BackendSettings = request.app.state.settings
        return HealthResponse(status="ok", environment=current.environment, store_backend=current.store_backend)

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

    return application


app = create_app()
