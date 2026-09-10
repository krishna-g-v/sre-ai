from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_superuser
from app.db.models import Group, User, UserGroupMembership
from app.db.session import get_db
from app.schemas.users import GroupCreate, GroupOut, GroupUpdate, MembershipUpdate, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/groups", response_model=list[GroupOut])
def list_groups(db: Session = Depends(get_db), _: CurrentUser = Depends(require_superuser)) -> list[Group]:
    return list(db.execute(select(Group)).scalars().all())


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(
    payload: GroupCreate, db: Session = Depends(get_db), _: CurrentUser = Depends(require_superuser)
) -> Group:
    group = Group(name=payload.name, description=payload.description)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.put("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_superuser),
) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    db.commit()
    db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(
    group_id: UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(require_superuser)
) -> None:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    db.delete(group)
    db.commit()


def _user_out(db: Session, user: User) -> UserOut:
    group_ids = [
        m.group_id
        for m in db.execute(select(UserGroupMembership).where(UserGroupMembership.user_id == user.id)).scalars()
    ]
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_superuser=user.is_superuser,
        group_ids=group_ids,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: CurrentUser = Depends(require_superuser)) -> list[UserOut]:
    users = db.execute(select(User)).scalars().all()
    return [_user_out(db, u) for u in users]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate, db: Session = Depends(get_db), _: CurrentUser = Depends(require_superuser)
) -> UserOut:
    existing = db.execute(select(User).where(User.username == payload.username)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=payload.username,
        password=payload.password,  # plaintext v1 — see docs/05-auth-and-users.md
        display_name=payload.display_name,
        is_superuser=payload.is_superuser,
    )
    db.add(user)
    db.flush()

    for group_id in payload.group_ids:
        db.add(UserGroupMembership(user_id=user.id, group_id=group_id))

    db.commit()
    return _user_out(db, user)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_superuser),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.is_superuser is False and user.is_superuser:
        remaining_superusers = db.execute(
            select(User).where(User.is_superuser.is_(True), User.id != user_id)
        ).first()
        if remaining_superusers is None:
            raise HTTPException(status_code=400, detail="Cannot remove the last remaining superuser")

    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.password is not None:
        user.password = payload.password  # plaintext v1 — see docs/05-auth-and-users.md
    if payload.is_superuser is not None:
        user.is_superuser = payload.is_superuser

    db.commit()
    return _user_out(db, user)


@router.put("/users/{user_id}/groups", response_model=UserOut)
def update_user_groups(
    user_id: UUID,
    payload: MembershipUpdate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_superuser),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.execute(select(UserGroupMembership).where(UserGroupMembership.user_id == user_id)).scalars().all()
    for m in existing:
        db.delete(m)
    db.flush()

    for group_id in payload.group_ids:
        db.add(UserGroupMembership(user_id=user_id, group_id=group_id))

    db.commit()
    return _user_out(db, user)
