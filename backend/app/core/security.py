"""
v1 auth is intentionally simple: plaintext password compare, no hashing.
This is a deliberate, documented simplification (docs/05-auth-and-users.md) — not a bug.
Replace with a real password hash + Microsoft Entra ID before this ever handles real
production credentials.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def verify_password(plain_password: str, stored_password: str) -> bool:
    return plain_password == stored_password


def create_access_token(*, user_id: UUID, username: str, group_ids: list[str], is_superuser: bool) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "group_ids": group_ids,
        "is_superuser": is_superuser,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
