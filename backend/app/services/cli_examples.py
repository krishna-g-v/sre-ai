"""Few-shot (question -> command) examples for NL-to-CLI generation —
docs/10-nl-to-cli-execution.md §6.

Implementation note vs. the original docs/10 design: that doc sketched storing these
as tagged documents in the KB (kb.documents/kb.chunks), retrieved through the normal
RAG path. This module implements the same *idea* — semantic retrieval over a curated
corpus using the same embedding model as the rest of the system — without going
through Postgres/kb.documents, since these examples aren't user content, don't need
group-based access control (there's nothing sensitive in a generic "how do you list
EKS nodegroups" example), and a KB round-trip would be a heavier dependency for what's
really an in-process lookup table. Swapping this for real kb.documents storage later
(e.g. once auto-growth from validated executions is built, per docs/10 §1) is a
contained change — only `get_similar_examples`'s implementation, not its callers.

Manually curated for now (docs/10 §1) — add to EXAMPLES as real questions come up in
use; nothing here grows automatically yet.
"""

from functools import lru_cache

from app.services.embeddings import embed_documents, embed_query

EXAMPLES: list[dict[str, str]] = [
    {
        "question": "what version is the eks cluster on",
        "command": "aws eks describe-cluster --name {cluster_name}",
    },
    {
        "question": "list the nodegroups in this cluster",
        "command": "aws eks list-nodegroups --cluster-name {cluster_name}",
    },
    {
        "question": "what ami/version are the nodes in nodegroup X running",
        "command": "aws eks describe-nodegroup --cluster-name {cluster_name} --nodegroup-name {nodegroup_name}",
    },
    {
        "question": "what addons are installed on the cluster",
        "command": "aws eks list-addons --cluster-name {cluster_name}",
    },
    {
        "question": "what version is the vpc-cni/coredns/kube-proxy addon",
        "command": "aws eks describe-addon --cluster-name {cluster_name} --addon-name {addon_name}",
    },
    {
        "question": "list the pods in the payments namespace",
        "command": "kubectl get pods -n {namespace}",
    },
    {
        "question": "why is pod X crashlooping",
        "command": "kubectl describe pod {pod_name} -n {namespace}",
    },
    {
        "question": "show me the logs for pod X",
        "command": "kubectl logs {pod_name} -n {namespace} --tail=200",
    },
    {
        "question": "show me the previous container's logs after a crash",
        "command": "kubectl logs {pod_name} -n {namespace} --previous --tail=200",
    },
    {
        "question": "what's the rollout status of the checkout deployment",
        "command": "kubectl get deployment {deployment_name} -n {namespace}",
    },
    {
        "question": "what events happened in this namespace recently",
        "command": "kubectl get events -n {namespace} --sort-by=.lastTimestamp",
    },
    {
        "question": "how much cpu/memory are pods using in this namespace",
        "command": "kubectl top pods -n {namespace}",
    },
    {
        "question": "how many ec2 instances/VMs are running in this account",
        "command": "aws ec2 describe-instances --query 'length(Reservations[].Instances[])'",
    },
    {
        "question": "list the ec2 instances and their state",
        "command": "aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table",
    },
    {
        "question": "how many ebs volumes are there and which is the largest",
        "command": "aws ec2 describe-volumes --query '{count: length(Volumes), largest: sort_by(Volumes, &Size)[-1].[VolumeId,Size]}'",
    },
    {
        "question": "what subnets exist in this vpc",
        "command": "aws ec2 describe-subnets --filters Name=vpc-id,Values={vpc_id}",
    },
    {
        "question": "what security groups are attached to this vpc",
        "command": "aws ec2 describe-security-groups --filters Name=vpc-id,Values={vpc_id}",
    },
    {
        "question": "describe this vpc's cidr and settings",
        "command": "aws ec2 describe-vpcs --vpc-ids {vpc_id}",
    },
    {
        "question": "is this target group healthy",
        "command": "aws elbv2 describe-target-health --target-group-arn {target_group_arn}",
    },
    {
        "question": "list the ecr repositories",
        "command": "aws ecr describe-repositories",
    },
    {
        "question": "how big is this ecr repo / list its images",
        "command": "aws ecr describe-images --repository-name {repo_name}",
    },
    {
        "question": "search cloudwatch logs for an error string",
        "command": 'aws logs filter-log-events --log-group-name {log_group} --filter-pattern "{search_term}"',
    },
    {"question": "what log groups exist", "command": "aws logs describe-log-groups"},
    {
        "question": "what's the cpu utilization metric for this instance/service",
        "command": "aws cloudwatch get-metric-data --metric-data-queries {query_spec} --start-time {start} --end-time {end}",
    },
    {
        "question": "describe the rds instance's engine version and status",
        "command": "aws rds describe-db-instances --db-instance-identifier {db_instance_id}",
    },
    {
        "question": "list the rds snapshots for this instance",
        "command": "aws rds describe-db-snapshots --db-instance-identifier {db_instance_id}",
    },
]


@lru_cache
def _example_vectors() -> list[list[float]]:
    return embed_documents([e["question"] for e in EXAMPLES])


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def get_similar_examples(question: str, k: int = 5) -> list[dict[str, str]]:
    """Top-k examples by cosine similarity. Vectors from embed_documents/embed_query are
    already unit-normalized, so a plain dot product is the cosine similarity — no need
    for numpy for a corpus this small."""
    query_vector = embed_query(question)
    scored = sorted(
        zip(EXAMPLES, _example_vectors()),
        key=lambda pair: _dot(query_vector, pair[1]),
        reverse=True,
    )
    return [example for example, _ in scored[:k]]
