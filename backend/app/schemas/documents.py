from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: UUID
    title: str
    source_filename: str
    uploaded_by: UUID
    uploaded_at: datetime
    owner_scope: str
    group_ids: list[UUID]
    personal_owner_id: UUID | None
    content_type: str
    status: str
    tags: list[str]
    chunk_strategy: str
    best_effort_target_size: str | None
    converted_to_markdown: bool

    class Config:
        from_attributes = True
