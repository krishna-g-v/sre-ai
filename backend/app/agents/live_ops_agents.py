"""Live-ops domain tools — docs/03-agent-and-integrations.md §2, §4.

All read-only by construction: no mutating call exists in this module for the LLM to
invoke, and each function first checks the group's `integration_scope` config — an
engineer only gets live data for clusters/accounts/dashboards their groups are scoped to.

AWS/EKS-backed tools go through `app/services/aws_session.py` (docs/09 §2) rather than
calling `boto3`/`kubernetes` with ambient credentials directly, so a group whose scope
has no `role_arn` for an account simply can't reach it. Tools with no matching
`integration_scope` row resolve to a clear "not configured" response rather than
fabricating data — see docs/00-overview.md's advisory-only guardrail.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.integration_scopes import scopes_for as _scopes_for

NOT_CONFIGURED_MSG = (
    "No {integration} integration is configured for your group(s) yet. "
    "A superuser can add one under Admin → Integration Scopes."
)


def cloudwatch_query_logs(db: Session, group_ids: list[uuid.UUID], query: str) -> str:
    scopes = _scopes_for(db, group_ids, "aws_cloudwatch")
    if not scopes:
        return NOT_CONFIGURED_MSG.format(integration="AWS CloudWatch")

    from app.services.aws_session import get_client

    default_region = get_settings().aws_region
    lines: list[str] = []
    for scope in scopes:
        log_group = scope.config.get("log_group")
        if not log_group:
            continue
        client = get_client(scope.config, "logs", default_region=default_region)
        response = client.filter_log_events(logGroupName=log_group, filterPattern=query, limit=20)
        lines.extend(e["message"] for e in response.get("events", []))
    return "\n".join(lines) if lines else "No matching log events found."


def k8s_get_pods(db: Session, group_ids: list[uuid.UUID], namespace: str) -> str:
    scopes = _scopes_for(db, group_ids, "eks")
    if not scopes:
        return NOT_CONFIGURED_MSG.format(integration="EKS/kubectl")

    from app.services.aws_session import get_k8s_client

    default_region = get_settings().aws_region
    lines: list[str] = []
    for scope in scopes:
        cluster_name = scope.config.get("cluster_name", "unknown")
        try:
            v1 = get_k8s_client(scope.config, default_region=default_region)
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
