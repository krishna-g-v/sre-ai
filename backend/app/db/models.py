import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # BAAI/bge-large-en-v1.5 — see docs/02-access-control-and-rag.md §5


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ---------------------------------------------------------------------------
# Users & dynamic groups — docs/05-auth-and-users.md
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)  # plaintext v1 — see docs/05
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    memberships: Mapped[list["UserGroupMembership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserGroupMembership(Base):
    __tablename__ = "user_group_memberships"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_user_group"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)

    user: Mapped["User"] = relationship(back_populates="memberships")
    group: Mapped["Group"] = relationship()


# ---------------------------------------------------------------------------
# Integration scope — docs/03-agent-and-integrations.md §4
# ---------------------------------------------------------------------------


class IntegrationScope(Base):
    __tablename__ = "integration_scope"

    id: Mapped[uuid.UUID] = uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    integration_type: Mapped[str] = mapped_column(String(50), nullable=False)  # aws_cloudwatch | eks | grafana | prometheus
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# kb schema — document knowledge base, docs/02-access-control-and-rag.md
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"schema": "kb"}

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner_scope: Mapped[str] = mapped_column(String(20), nullable=False)  # group | personal
    group_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    personal_owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    content_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf | docx | md | txt
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    chunk_strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="whole_document")
    best_effort_target_size: Mapped[str | None] = mapped_column(String(10), nullable=True)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = {"schema": "kb"}

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb.documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(20), nullable=False)  # whole_document | best_effort
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped["Document"] = relationship(back_populates="chunks")


# ---------------------------------------------------------------------------
# ops schema — operational/log data, docs/02-access-control-and-rag.md §6
# ---------------------------------------------------------------------------


class OpsSource(Base):
    __tablename__ = "sources"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)


class OpsEvent(Base):
    __tablename__ = "events"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.sources.id", ondelete="CASCADE"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# Chat sessions & orchestration — docs/08-chat-sessions-and-orchestration.md
# ---------------------------------------------------------------------------


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="New Chat")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="general")  # general | pinned
    pinned_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kb.documents.id", ondelete="SET NULL"), nullable=True
    )
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    pinned_document: Mapped["Document | None"] = relationship(foreign_keys=[pinned_document_id])

    @property
    def pinned_document_title(self) -> str | None:
        return self.pinned_document.title if self.pinned_document else None


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_category: Mapped[str | None] = mapped_column(String(20), nullable=True)  # general | document_topic | live_ops
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Alert triage — Agents (pluggable triage bots) & Alerts (ingested + triaged).
# Not part of the original docs; added per follow-up request to match the
# dashboard/alerts/agent-studio pages of the reference app. Advisory only, same
# guardrail as everything else: auto_remediation_enabled is a stored preference,
# never actually executed — see docs/00-overview.md.
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # Grafana|Synthetics|Prometheus|Kubernetes|CloudWatch|Custom
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="webhook")
    webhook_path: Mapped[str] = mapped_column(String(255), nullable=False)
    triage_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity_rule: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auto_remediation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)  # empty = org-wide
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_triaged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    real_issues_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    noise_filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = uuid_pk()
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # same categories as Agent.category
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Firing")  # Firing|Resolved|Triaged
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="Warning")  # Critical|Warning|Info
    verdict: Mapped[str] = mapped_column(String(20), nullable=False, default="Investigating")  # Real Incident|Filtered Noise|Investigating
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    annotations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    canary_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canary_start_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    canary_end_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    canary_error_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canary_error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    canary_steps: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    runbook_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    triage_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    group_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)  # empty = org-wide
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
