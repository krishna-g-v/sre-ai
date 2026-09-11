"""Per-user Settings — docs/10-nl-to-cli-execution.md §9.

Every route here is scoped to the requesting user's own rows only, including for
superusers — there is deliberately no admin view of other users' registered AWS
accounts (see UserAwsAccount's docstring in app/db/models.py for why).

Responses use UserAwsAccountOut.from_model explicitly (not FastAPI's automatic
from_attributes mapping) specifically so `secret_access_key` never round-trips back to
the client once saved — only a `has_own_credentials` boolean does.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.db.models import UserAwsAccount
from app.db.session import get_db
from app.schemas.settings import (
    UserAwsAccountCreate,
    UserAwsAccountOut,
    UserAwsAccountUpdate,
)

router = APIRouter(prefix="/settings/aws-accounts", tags=["settings"])


def _get_owned_account(
    db: Session, account_id: UUID, user: CurrentUser
) -> UserAwsAccount:
    account = db.get(UserAwsAccount, account_id)
    if account is None or account.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="AWS account not found")
    return account


@router.get("", response_model=list[UserAwsAccountOut])
def list_my_aws_accounts(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[UserAwsAccountOut]:
    stmt = (
        select(UserAwsAccount)
        .where(UserAwsAccount.user_id == user.user_id)
        .order_by(UserAwsAccount.label)
    )
    accounts = db.execute(stmt).scalars().all()
    return [UserAwsAccountOut.from_model(a) for a in accounts]


@router.post("", response_model=UserAwsAccountOut, status_code=201)
def add_aws_account(
    payload: UserAwsAccountCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> UserAwsAccountOut:
    account = UserAwsAccount(user_id=user.user_id, **payload.model_dump())
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"You already have an account labeled '{payload.label}'.",
        )
    db.refresh(account)
    return UserAwsAccountOut.from_model(account)


@router.patch("/{account_id}", response_model=UserAwsAccountOut)
def update_aws_account(
    account_id: UUID,
    payload: UserAwsAccountUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> UserAwsAccountOut:
    account = _get_owned_account(db, account_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return UserAwsAccountOut.from_model(account)


@router.delete("/{account_id}", status_code=204)
def delete_aws_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    account = _get_owned_account(db, account_id, user)
    db.delete(account)
    db.commit()
