from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.models import User, UserGroupMembership
from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    group_ids = [
        m.group_id
        for m in db.execute(
            select(UserGroupMembership).where(UserGroupMembership.user_id == user.id)
        ).scalars()
    ]

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        group_ids=[str(g) for g in group_ids],
        is_superuser=user.is_superuser,
    )

    return LoginResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_superuser=user.is_superuser,
        group_ids=group_ids,
    )
