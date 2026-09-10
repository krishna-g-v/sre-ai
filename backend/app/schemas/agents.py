from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AgentOut(BaseModel):
    id: UUID
    name: str
    description: str
    owner: str
    category: str
    enabled: bool
    trigger_type: str
    webhook_path: str
    triage_prompt: str
    severity_rule: str
    auto_remediation_enabled: bool
    group_ids: list[UUID]
    last_run_at: datetime | None
    total_triaged: int
    real_issues_detected: int
    noise_filtered_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    owner: str = ""
    category: str = "Custom"  # Grafana | Synthetics | Prometheus | Kubernetes | CloudWatch | Custom
    triage_prompt: str = "Evaluate alert parameters, separate transient noise from true outage, and provide remediation steps."
    severity_rule: str = "Set Critical if service outage or threshold breach > 90%."
    group_ids: list[UUID] = []
