"""Live-ops domain tools — docs/03-agent-and-integrations.md §2, §4.

All read-only by construction: no mutating call exists in this module for the LLM to
invoke, and each function first checks the group's `integration_scope` config — an
engineer only gets live data for clusters/accounts/dashboards their groups are scoped to.

None of these have live credentials in this dev sandbox (no AWS account, EKS cluster,
Grafana, or Prometheus wired up here), so they resolve to a clear "not configured"
response rather than fabricating data — see docs/00-overview.md's advisory-only guardrail.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IntegrationScope

NOT_CONFIGURED_MSG = (
    "No {integration} integration is configured for your group(s) yet. "
    "A superuser can add one under Admin → Integration Scopes."
)


def _scopes_for(db: Session, group_ids: list[uuid.UUID], integration_type: str) -> list[IntegrationScope]:
    if not group_ids:
        return []
    stmt = select(IntegrationScope).where(
        IntegrationScope.group_id.in_(group_ids),
        IntegrationScope.integration_type == integration_type,
    )
    return list(db.execute(stmt).scalars().all())


def cloudwatch_query_logs(db: Session, group_ids: list[uuid.UUID], query: str) -> str:
    scopes = _scopes_for(db, group_ids, "aws_cloudwatch")
    if not scopes:
        return NOT_CONFIGURED_MSG.format(integration="AWS CloudWatch")

    import boto3

    lines: list[str] = []
    for scope in scopes:
        log_group = scope.config.get("log_group")
        region = scope.config.get("region")
        if not log_group:
            continue
        client = boto3.client("logs", region_name=region)
        response = client.filter_log_events(logGroupName=log_group, filterPattern=query, limit=20)
        lines.extend(e["message"] for e in response.get("events", []))
    return "\n".join(lines) if lines else "No matching log events found."


def k8s_get_pods(db: Session, group_ids: list[uuid.UUID], namespace: str) -> str:
    scopes = _scopes_for(db, group_ids, "eks")
    if not scopes:
        return NOT_CONFIGURED_MSG.format(integration="EKS/kubectl")

    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config

    lines: list[str] = []
    for scope in scopes:
        cluster_name = scope.config.get("cluster_name", "unknown")
        kubeconfig_path = scope.config.get("kubeconfig_path")
        try:
            if kubeconfig_path:
                k8s_config.load_kube_config(config_file=kubeconfig_path)
            else:
                k8s_config.load_incluster_config()
            v1 = k8s_client.CoreV1Api()
            pods = v1.list_namespaced_pod(namespace=namespace)
            for pod in pods.items:
                lines.append(f"[{cluster_name}] {pod.metadata.name}: {pod.status.phase}")
        except Exception as exc:  # pragma: no cover - depends on external cluster
            lines.append(f"[{cluster_name}] could not reach cluster: {exc}")
    return "\n".join(lines) if lines else f"No pods found in namespace '{namespace}'."


def grafana_get_active_alerts(db: Session, group_ids: list[uuid.UUID]) -> str:
    scopes = _scopes_for(db, group_ids, "grafana")
    if not scopes:
        return NOT_CONFIGURED_MSG.format(integration="Grafana")

    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    lines: list[str] = []
    for scope in scopes:
        base_url = scope.config.get("base_url", settings.grafana_base_url)
        api_key = scope.config.get("api_key", settings.grafana_api_key)
        if not base_url:
            continue
        response = httpx.get(
            f"{base_url}/api/alertmanager/grafana/api/v2/alerts",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        for alert in response.json():
            lines.append(alert.get("labels", {}).get("alertname", "unknown alert"))
    return "\n".join(lines) if lines else "No active Grafana alerts."


def prometheus_instant_query(db: Session, group_ids: list[uuid.UUID], promql: str) -> str:
    scopes = _scopes_for(db, group_ids, "prometheus")
    if not scopes:
        return NOT_CONFIGURED_MSG.format(integration="Prometheus")

    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    results: list[str] = []
    for scope in scopes:
        base_url = scope.config.get("base_url", settings.prometheus_base_url)
        if not base_url:
            continue
        response = httpx.get(f"{base_url}/api/v1/query", params={"query": promql}, timeout=10)
        response.raise_for_status()
        results.append(str(response.json().get("data", {}).get("result", [])))
    return "\n".join(results) if results else "No results."
