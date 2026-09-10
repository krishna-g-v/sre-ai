from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class AlertOut(BaseModel):
    id: UUID
    agent_id: UUID | None
    agent_name: str
    source: str
    title: str
    occurred_at: datetime
    status: str
    severity: str
    verdict: str
    raw_payload: dict[str, Any]
    labels: dict[str, str]
    annotations: dict[str, str]
    canary_name: str | None
    canary_start_url: str | None
    canary_end_url: str | None
    canary_error_step: str | None
    canary_error_msg: str | None
    canary_steps: list[dict[str, Any]] | None
    runbook_link: str | None
    triage_report: dict[str, Any] | None
    group_ids: list[UUID]
    created_at: datetime

    class Config:
        from_attributes = True


SampleType = Literal["grafana_cpu", "grafana_memory", "synthetics_login", "prometheus_slow", "custom"]


class SampleTriggerRequest(BaseModel):
    sample_type: SampleType
    custom_payload: dict[str, Any] | None = None
    category: str | None = None


class WebhookPayload(BaseModel):
    """Loosely typed — real alertmanager/synthetics/prometheus webhook shapes vary widely;
    we accept whatever JSON body is posted and pull known fields out of it defensively."""

    model_config = {"extra": "allow"}
