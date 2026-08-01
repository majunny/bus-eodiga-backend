"""Firebase ID Token 검증 의존성."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth

from backend.config import BackendSettings


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    """검증된 Firebase 사용자의 최소 정보."""

    uid: str


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """Bearer Firebase ID Token을 검증하고 UID를 반환한다."""

    settings: BackendSettings = request.app.state.settings
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    token = credentials.credentials
    if settings.allow_dev_auth and token == settings.dev_auth_token:
        return AuthenticatedUser(uid="local-demo-user")

    try:
        decoded = auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Firebase ID token") from exc

    uid = decoded.get("uid") or decoded.get("sub")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has no uid")
    return AuthenticatedUser(uid=str(uid))
