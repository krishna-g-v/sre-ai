from sqlalchemy import select
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user
from app.db.models import Group
from app.db.session import get_db
from app.schemas.users import GroupOut

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("/mine", response_model=list[GroupOut])
def list_my_groups(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[Group]:
    """Any authenticated user can see the groups they belong to (not full admin CRUD —
    that's /admin/groups, superuser-only) — needed so they can pick a target group when
    uploading a document. Superusers see every group, since they can upload on behalf of any."""
    if user.is_superuser:
        return list(db.execute(select(Group)).scalars().all())
    if not user.group_ids:
        return []
    return list(db.execute(select(Group).where(Group.id.in_(user.group_ids))).scalars().all())
