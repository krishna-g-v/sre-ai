# Ops Runbook Assistant & Proactive EKS Monitoring

See [[00-overview]], [[01-architecture]], [[03-agent-and-integrations]] (tool contracts/guardrails this extends), [[02-access-control-and-rag]] (RAG reused here for runbook retrieval).

This doc covers two new day-to-day-SRE capabilities layered on the existing advisory-only, group-scoped architecture: (1) a change/runbook assistant for tasks like EKS upgrades and new deployments, and (2) extended read-only monitoring (EKS, ECR, network) plus proactive pod-breakdown alerting. Nothing here adds a mutating tool or changes the v1 advisory-only guardrail (see [[03-agent-and-integrations]] §3) — it extends the read-only tool surface and reuses the existing `Agent`/`Alert`/triage pipeline (`backend/app/api/routes/alerts.py`, `backend/app/services/triage.py`) that already exists for Grafana/Synthetics/Prometheus.

## 1. Decisions (confirmed with the user, 2026-09-10)

| Topic | Decision |
|---|---|
| Cross-account AWS access | AssumeRole from one central identity — dev uses the operator's AWS CLI profile, prod uses an IRSA role on the cluster the backend runs on. Each target account gets a purpose-built read-only IAM role; the backend assumes it via STS. No static per-account access keys. |
| Product grouping (for incident timelines) | Admin-configured mapping only (a new `product_groups` table), not label-inference or ad hoc per-question lists — consistent with the existing "no auto-discovery" principle ([[03-agent-and-integrations]] §5). |
| Runbook/change-assistant output | Exact CLI/eksctl/kubectl command steps only, grounded in real discovered state. No generated files/manifests in this phase. |
| Pod-breakdown monitoring | Proactive polling + alerting now (not deferred to a later phase), reusing the existing `Agent`/`Alert`/AI-triage pipeline rather than inventing a new one. |
| Alert delivery channel | In-app only (existing alerts UI/API). Slack/email are explicitly deferred — the poller's alert-creation path is the same one webhook sources already use, so adding a channel later is additive, not a rework. |
| Alert triggers (default, tunable) | CrashLoopBackOff / restart-count spike, OOMKilled, and Failed/Pending pod stuck past a grace period. Deployment-rollout-stuck is deferred, not decided against — can be added the same way later. |

## 2. Multi-account AWS access

Extend `IntegrationScope.config` (`backend/app/db/models.py`) with:

```
config:
  account_id: string
  role_arn: string          # e.g. arn:aws:iam::<account>:role/sre-agent-readonly
  external_id: string | null
  region: string
  cluster_names: [string]   # for eks-type scopes
  ...                       # existing per-type keys unchanged (log_group, base_url, etc.)
```

A small helper (`backend/app/services/aws_session.py`, new) wraps `sts.assume_role(role_arn, external_id)` and caches the resulting boto3 `Session` per scope until shortly before credential expiry (default STS session is 1h). Every AWS-backed tool in `live_ops_agents.py` goes through this helper instead of calling `boto3.client(...)` directly with ambient credentials, so an account with no `role_arn` configured for the user's group simply isn't reachable — same "explicit config only" boundary as today.

**Target-account setup (outside this repo, done once per account you onboard):**
- An IAM role (e.g. `sre-agent-readonly`) whose trust policy allows the backend's base identity to assume it (optionally gated by `external_id`).
- A **curated** read-only policy attached to it — not the AWS-managed `ReadOnlyAccess` policy, which is far broader than this needs (it includes IAM/billing/every-service read access). Scope it to what the tool surface below actually calls: `eks:Describe*`, `eks:List*`, `ecr:Describe*`, `ecr:List*`, `ec2:Describe*`, `elasticloadbalancing:Describe*`, `cloudwatch:GetMetricData`, `cloudwatch:ListMetrics`, `logs:StartQuery`, `logs:GetQueryResults`, `logs:FilterLogEvents`, `logs:DescribeLogGroups`.
- For EKS API access specifically, the assumed role also needs to be mapped to a **view-only Kubernetes RBAC identity** in each cluster — either an EKS access entry or an `aws-auth` ConfigMap mapping to a `ClusterRole` restricted to `get`/`list`/`watch` (this is the standard "IAM role ≠ automatic k8s RBAC" gap; both layers must be granted). This mirrors the guardrail already described in [[03-agent-and-integrations]] §2 — no `create`/`update`/`patch`/`delete` on either side.

## 3. Fill out the read-only tool surface

`backend/app/agents/live_ops_agents.py` currently implements only `cloudwatch_query_logs`, `k8s_get_pods`, `grafana_get_active_alerts`, `prometheus_instant_query`. Add:

- `k8s_describe_pod`, `k8s_get_pod_logs`, `k8s_get_events`, `k8s_get_deployment_status`, `k8s_list_deployments` — already named in [[03-agent-and-integrations]] §2's tool contract, not yet implemented; `k8s_list_deployments` is new (needed to resolve a product group's members, §5).
- `cloudwatch_get_metric` — also already named in the contract, not yet implemented.
- `eks_describe_cluster(cluster) -> version, platform_version, addon versions, nodegroup AMI release` — new; grounds the runbook assistant's upgrade plans in real current state (§4).
- `ecr_list_repositories(scope) -> [{repo_name, image_count, total_size_bytes, last_pushed_at}]`, `ecr_list_images(repo, limit) -> [{tag, digest, size_bytes, pushed_at}]` — new integration type `ecr`. Sizes come straight from `describe-images`' `imageSizeInBytes`; no layer download needed.
- `ec2_describe_vpc`, `ec2_list_subnets`, `ec2_list_security_groups`, `elbv2_describe_target_health` — new integration type `aws_network`, for "what does the network around this cluster look like" questions.

All of these are read/describe/list/get calls only — same guardrail as existing tools (no new entry point for a mutating call).

For live-ops questions that don't match one of these fixed functions, [[10-nl-to-cli-execution]] adds a complementary fallback: the LLM generates an actual `aws`/`kubectl` command (RAG few-shot, text-to-SQL-style) which is validated against a read-only allowlist and executed directly, rather than requiring a new hand-written function for every question shape.

## 4. Ops Runbook / Change-Assistant

A new capability, not a new agent-autonomy tier: when a `live_ops` message reads as a task/change request ("upgrade X", "create a deployment for Y in VPC Z") rather than a pure status question, the flow is:

1. Extract task parameters from the message + conversation history (cluster, target version, resource type, VPC/namespace/service name).
2. Call the read-only discovery tools above to fetch real current state (current EKS/addon/nodegroup versions, existing subnets/security groups, an existing comparable deployment as a template).
3. Retrieve relevant internal runbooks via the existing RAG retrieval (`app/services/retrieval.py`), scoped to the user's groups exactly as document Q&A already is — upload your EKS-upgrade runbook / deployment checklist as a tagged document and it's usable here with no new ingestion path.
4. Synthesize an ordered list of exact commands (`aws eks ...`, `eksctl ...`, `kubectl ...`, `helm ...`) with real discovered IDs substituted in, plus prerequisites, risk flags, and a rollback note. Rendered as text/Markdown in chat — never invoked as a tool call, per the existing "proposed command is text output, not a tool invocation" guardrail ([[03-agent-and-integrations]] §3).
5. Follow-up turns (the "cowork" loop): the user pastes command output back in; the agent interprets it and proposes the next step. This needs no new session-state mechanism — it's the same conversation-history-aware flow already described in [[08-chat-sessions-and-orchestration]] §8.

No new tool registry entry is mutating. This sits inside the Supervisor/EKS-kubectl subgraph from [[03-agent-and-integrations]] §1, not a new subgraph type.

## 5. Runbook corpus: what to ingest, and how it improves over time

The Runbook/Change-Assistant (§4) is only as good as what's in the document KB plus what the live discovery tools can see *right now* — it is RAG (retrieve chunks, ground the answer in them), not model fine-tuning. Nothing here trains on your data; "learning" means the corpus growing and being kept accurate, and that only happens when someone uploads something. This section is the ingestion plan so that dependency is explicit instead of assumed.

**Two kinds of data — keep them in separate places, don't put both in documents:**

- **Narrative/procedural knowledge → the document KB (RAG).** Things explained in prose: how to do a task, why a decision was made, what happened last time something broke. This is what §4 retrieves from.
- **Structured operational facts → config + live tools, never a document.** Cluster names, account IDs, VPC/subnet IDs, role ARNs, which deployments belong to which product. These change and must stay authoritative — this is exactly what `integration_scope` (§2) and `product_groups` (§6) are for, resolved live at query time via the read-only discovery tools (§3), not read from a doc someone forgot to update. A doc claiming "prod cluster is `eks-prod-v3`" goes stale the day it's renamed; a live `eks_describe_cluster` call never does.

**What to upload, in priority order:**

| Phase | Content | Tagging |
|---|---|---|
| A — minimum useful | EKS upgrade runbook(s): version sequence, addon compatibility notes, nodegroup AMI rotation, cordon/drain/PDB handling, rollback steps. New-deployment checklist: namespace/labeling conventions, resource request/limit policy, network policy rules, ingress/ALB conventions, secrets convention, approval process if any. Existing wiki/Confluence exports for these, as-is — don't polish first, retrieval works fine on messy real docs. | `task_type: eks_upgrade` / `task_type: new_deployment` |
| B — sharper answers, doubles as fuel for an existing feature | Past incident postmortems (crashloops, OOMs, network issues, bad rollouts). These also directly sharpen the *existing* alert-triage feature, since `triage.py::generate_ai_triage` already retrieves KB context when triaging incoming alerts (§6) — uploading postmortems improves both features from one action. An escalation/ownership map (who owns what, who to page). | `postmortem` / `escalation`, plus the service/product name |
| C — the actual feedback loop | After a runbook-assisted change, a short note on what actually happened and any deviation from the plan, uploaded back with the same tags as the original runbook. Periodically, a notable resolved `Alert.triage_report` worth remembering, promoted to a proper doc. | same tags as the runbook/task it followed up on |

Phase C is the one genuine "gets better automatically" mechanism: the assistant doesn't infer outcomes on its own, so the loop only closes if the outcome is written back in. Skipping it means every future answer is only ever as good as the original runbook, never improved by having actually done the work.

**Chunking:** runbooks are usually multi-section (prerequisites / steps / rollback) and often cover more than one task. Use `best_effort` chunking (per-document override at upload time, [[02-access-control-and-rag]] §3) rather than `whole_document`, so a question about the rollback section retrieves just that section instead of the whole upgrade doc.

## 6. Cross-app incident timeline

New table:

```
product_groups:
  id: uuid
  group_id: group_id          # which org group owns/can see this product mapping
  name: string                # e.g. "checkout", "payments-platform"
  members: jsonb               # [{cluster, namespace, deployment}]
```

Superuser-managed CRUD, same permission model as `integration_scope` (admin-only creation, per [[02-access-control-and-rag]] §8) — deliberately not auto-discovered, per the confirmed decision in §1. See §5 for what to feed the RAG side of this same investigation flow.

New tool `build_incident_timeline(product_group_id, time_range)`:
- Resolves the product's member deployments via `product_groups`.
- Fans out `k8s_get_pod_logs` + `k8s_get_events` (and `cloudwatch_query_logs` where the group also has a CloudWatch scope) across every member.
- Merges all returned entries by timestamp, tagging each with its source cluster/namespace/pod/deployment.
- Hands the merged, chronological list to the LLM to narrate: first error, cascade path, recovery point — each claim traceable back to a specific pod/deployment entry (same citation-transparency principle as [[01-architecture]] §4 step 7).

Chat entry point: "what happened to checkout in the last 2 hours" → `live_ops` classification → Supervisor routes to this tool via the EKS/kubectl subgraph.

## 7. Proactive EKS pod-breakdown monitoring

This reuses the **existing** `Agent` / `Alert` / AI-triage pipeline (`backend/app/db/models.py`, `backend/app/api/routes/alerts.py`, `backend/app/services/triage.py`) instead of building a parallel one — that pipeline already does exactly "ingest a raw payload → AI-triage it against the KB → produce root-cause + step-by-step remediation → store as an `Alert` with `status`/`severity`/`verdict`" for Grafana/Synthetics/Prometheus webhook sources. `Agent.category` already includes `"Kubernetes"` and `Agent.trigger_type` already exists as a field (currently only `"webhook"` is used) — a Kubernetes-category agent with a new `trigger_type = "poller"` slots into the existing model with no schema redesign.

**New pieces:**
- A lightweight in-process scheduler (APScheduler running inside the FastAPI app — no new infra like Celery/Redis for this) that, on an interval (default e.g. 60s, configurable), runs a poll pass for every enabled `Agent` with `category = "Kubernetes"` and `trigger_type = "poller"`.
- The poll pass resolves the EKS `integration_scope`(s) reachable via that agent's `group_ids`, lists pods/events across their configured clusters/namespaces, and checks for (per the confirmed default triggers in §1): `CrashLoopBackOff` waiting reason, a restart-count jump above a threshold within the poll window, `OOMKilled` terminated reason, or a pod stuck `Failed`/`Pending` past a grace period (default 5 min, configurable).
- **Dedup/cooldown**: before creating a new `Alert`, check for an existing `Alert` with `status = "Firing"` and matching `labels` (cluster+namespace+pod+reason) created within a cooldown window (default e.g. 15 min) — the existing webhook path has no dedup because upstream Alertmanager already dedupes; a direct poller needs this itself so an ongoing CrashLoopBackOff doesn't spam a new alert every cycle.
- When a genuinely new condition is found, build a payload shaped like the existing webhook payloads (`{"labels": {"alertname", "cluster", "namespace", "pod"}, "annotations": {"message"}}`) and call the same ingestion path `alerts.py::_ingest()` (or a small internal variant of it) with `category="kubernetes"` — this automatically runs `generate_ai_triage()` (root cause hypothesis + step-by-step remediation, grounded in the KB) and stores the `Alert`, which the existing alerts UI/API already surfaces. No new UI, no new alert schema.
- Delivery is in-app only per §1 — because the poller goes through the same `_ingest()` path as external webhooks, adding Slack/email later is a channel added to that one path, not a rework of the poller.

## 8. Sequencing

1. **Foundation** — AssumeRole support in `IntegrationScope`/AWS session helper; fill out the stubbed k8s/CloudWatch tools; add ECR and network tool sets. Validate end-to-end against one real AWS account + one real EKS cluster before onboarding more accounts.
2. **Corpus** — upload the Phase A runbook content from §5 (EKS upgrade + new-deployment docs) so the Runbook/Change-Assistant has something to retrieve from the moment it's built, rather than shipping it against an empty KB. Can happen in parallel with (1) — it's just document upload, no dependency on any new tool.
3. **High-value agent behaviors** — `product_groups` table + admin CRUD + `build_incident_timeline`; the Runbook/Change-Assistant flow + `eks_describe_cluster`.
4. **Proactive monitoring** — the poller + dedup logic on top of the existing `Agent`/`Alert`/triage pipeline, using the trigger set from §1.

Each phase is independently useful and shippable — (1)+(2) together already upgrade the existing chat-based monitoring from stubs to real, grounded answers; (3) and (4) can land in either order once (1) is done. Phase B/C content from §5 (postmortems, escalation map, outcome notes) keeps arriving continuously after launch, not as a one-time step.
