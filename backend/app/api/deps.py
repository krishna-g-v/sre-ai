from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

bearer_scheme = HTTPBearer()


class CurrentUser:
    def __init__(self, user_id: UUID, username: str, group_ids: list[UUID], is_superuser: bool):
        self.user_id = user_id
        self.username = username
        self.group_ids = group_ids
        self.is_superuser = is_superuser


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    return CurrentUser(
        user_id=UUID(payload["sub"]),
        username=payload["username"],
        group_ids=[UUID(g) for g in payload.get("group_ids", [])],
        is_superuser=payload.get("is_superuser", False),
    )


def require_superuser(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser access required")
    return user
