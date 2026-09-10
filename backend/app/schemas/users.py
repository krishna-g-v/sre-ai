from uuid import UUID

from pydantic import BaseModel


class GroupOut(BaseModel):
    id: UUID
    name: str
    description: str

    class Config:
        from_attributes = True


class GroupCreate(BaseModel):
    name: str
    description: str = ""


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    is_superuser: bool
    group_ids: list[UUID]


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str
    is_superuser: bool = False
    group_ids: list[UUID] = []


class MembershipUpdate(BaseModel):
    group_ids: list[UUID]


class UserUpdate(BaseModel):
    display_name: str | None = None
    password: str | None = None  # leave unset to keep the current password unchanged
    is_superuser: bool | None = None
