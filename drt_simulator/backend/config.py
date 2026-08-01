"""환경변수 기반 백엔드 설정."""

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    """Render와 로컬 환경에서 공통으로 사용하는 서버 설정."""

    app_name: str = "BUS어디가 API"
    environment: str = "development"
    store_backend: str = "memory"
    firebase_project_id: str = ""
    firebase_credentials_json: str = ""
    allow_dev_auth: bool = False
    enable_demo_dispatch: bool = False
    demo_group_size: int = Field(default=3, ge=2, le=6)
    demo_auto_simulation: bool = False
    demo_travel_seconds: float = Field(default=5.0, ge=0.2, le=60.0)
    demo_dwell_seconds: float = Field(default=2.0, ge=0.2, le=30.0)
    hardware_vehicle_control_enabled: bool = False
    vehicle_api_key: str = ""
    modi_kiosk_api_enabled: bool = False
    modi_kiosk_api_key: str = ""
    dev_auth_token: str = "local-demo-token"
    cors_origins: List[str] = Field(default_factory=list)
    osrm_base_url: str = "https://router.project-osrm.org"
    routing_timeout_seconds: float = Field(default=20.0, gt=0.0, le=60.0)
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    place_search_timeout_seconds: float = Field(default=10.0, gt=0.0, le=30.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> BackendSettings:
    """프로세스에서 재사용할 설정 인스턴스를 반환한다."""

    return BackendSettings()
