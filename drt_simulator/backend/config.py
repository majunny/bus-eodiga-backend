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
    dev_auth_token: str = "local-demo-token"
    cors_origins: List[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> BackendSettings:
    """프로세스에서 재사용할 설정 인스턴스를 반환한다."""

    return BackendSettings()
