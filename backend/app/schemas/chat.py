from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatSessionOut(BaseModel):
    id: UUID
    title: str
    status: str
    pinned_document_id: UUID | None
    pinned_document_title: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    message_category: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class SendMessageResponse(BaseModel):
    session: ChatSessionOut
    message: ChatMessageOut
    retrieved_titles: list[str] = []
    drifted: bool = False
