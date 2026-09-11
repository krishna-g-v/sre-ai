"""Cross-account AWS access — docs/09-ops-runbook-and-proactive-monitoring.md §2.

Every AWS/EKS-backed tool in `app/agents/live_ops_agents.py` goes through the helpers
here instead of calling `boto3`/`kubernetes` with ambient credentials directly, so a
group with no `role_arn` configured for an account simply can't reach it — the same
"explicit config only" boundary `integration_scope` already enforces for which
clusters/log groups/dashboards are reachable at all.

Expected `IntegrationScope.config` keys (all optional except where a tool requires
them): `role_arn`, `external_id`, `region`, `cluster_name` (EKS clusters — one scope
row per cluster, matching the existing `integration_scope` convention of one row per
resource), plus the pre-existing per-type keys (`log_group`, `base_url`, ...).

`config` may also carry `access_key_id`/`secret_access_key`/`session_token` — the base
identity to assume `role_arn` *as*, in place of the backend's own shared ambient
credentials (docs/10-nl-to-cli-execution.md §9: `UserAwsAccount` lets a user supply
their own base credentials instead of relying on one centrally-configured identity).
Optional; omitted falls back to ambient, unchanged from the original design.
"""

import base64
import tempfile
import threading
import time

import boto3
from botocore.model import ServiceId
from botocore.signers import RequestSigner

_STS_SERVICE_ID = ServiceId("sts")

_SESSION_NAME = "sre-agent"
_REFRESH_SKEW_SECONDS = (
    120  # refresh a bit before actual STS expiry, not at the deadline
)

_lock = threading.Lock()
_session_cache: dict[tuple[str, str, str | None, str], tuple[boto3.Session, float]] = {}
_ca_file_cache: dict[
    str, str
] = {}  # cluster endpoint -> path of a temp file holding its CA cert


def _base_session_kwargs(config: dict) -> dict:
    """The base identity to authenticate as, per config's access_key_id/secret_access_key
    (docs/10 §9) — empty dict falls through to boto3's default ambient chain."""
    access_key_id = config.get("access_key_id")
    if not access_key_id:
        return {}
    return {
        "aws_access_key_id": access_key_id,
        "aws_secret_access_key": config.get("secret_access_key"),
        "aws_session_token": config.get("session_token") or None,
    }


def get_aws_session(config: dict, *, default_region: str = "") -> boto3.Session:
    """A boto3 Session for the account/role an integration_scope/UserAwsAccount config
    describes.

    Falls back to the backend's own ambient credentials (dev: local AWS profile/env;
    prod: the IRSA role on the pod) when no `role_arn` is set, e.g. for resources in
    the same account the backend itself runs in.
    """
    region = config.get("region") or default_region
    role_arn = config.get("role_arn")
    base_kwargs = _base_session_kwargs(config)

    if not role_arn:
        return boto3.Session(region_name=region or None, **base_kwargs)

    external_id = config.get("external_id")
    # Cache key must identify *which base identity* is doing the assuming, not just
    # which role — two different base credentials (e.g. two different users' own keys,
    # docs/10 §9) assuming a same-named role string must never share a cached session.
    base_identity = base_kwargs.get("aws_access_key_id") or "ambient"
    cache_key = (base_identity, role_arn, external_id, region)

    with _lock:
        cached = _session_cache.get(cache_key)
        if cached is not None:
            session, expires_at = cached
            if expires_at - _REFRESH_SKEW_SECONDS > time.time():
                return session

        sts = boto3.client("sts", region_name=region or None, **base_kwargs)
        assume_kwargs = {"RoleArn": role_arn, "RoleSessionName": _SESSION_NAME}
        if external_id:
            assume_kwargs["ExternalId"] = external_id
        creds = sts.assume_role(**assume_kwargs)["Credentials"]

        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region or None,
        )
        _session_cache[cache_key] = (session, creds["Expiration"].timestamp())
        return session


def get_client(config: dict, service_name: str, *, default_region: str = ""):
    """A boto3 service client for `service_name`, using the session `get_aws_session`
    would return for this scope's account/role/region."""
    region = config.get("region") or default_region
    session = get_aws_session(config, default_region=region)
    return session.client(service_name, region_name=region or None)


def get_eks_bearer_token(session: boto3.Session, cluster_name: str, region: str) -> str:
    """Build an EKS-compatible bearer token from the session's credentials — the same
    presigned-STS-GetCallerIdentity trick `aws eks get-token`/aws-iam-authenticator
    use, done in pure Python via botocore so no extra CLI/binary is needed here."""
    signer = RequestSigner(
        _STS_SERVICE_ID,
        region,
        "sts",
        "v4",
        session.get_credentials(),
        session.events,
    )
    params = {
        "method": "GET",
        "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
        "body": {},
        "headers": {"x-k8s-aws-id": cluster_name},
        "context": {},
    }
    signed_url = signer.generate_presigned_url(
        params, region_name=region, expires_in=60, operation_name=""
    )
    token = (
        base64.urlsafe_b64encode(signed_url.encode("utf-8")).decode("utf-8").rstrip("=")
    )
    return f"k8s-aws-v1.{token}"


def _ca_cert_path(endpoint: str, ca_data_b64: str) -> str:
    """Cache the CA cert to a temp file per cluster endpoint instead of writing a new
    one on every call — this client is short-lived per tool invocation but the server
    process is long-running, so an unbounded per-call cache would leak temp files."""
    with _lock:
        cached = _ca_file_cache.get(endpoint)
        if cached:
            return cached
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".crt", delete=False
        ) as ca_file:
            ca_file.write(base64.b64decode(ca_data_b64))
            path = ca_file.name
        _ca_file_cache[endpoint] = path
        return path


def get_k8s_client(config: dict, *, default_region: str = ""):
    """A kubernetes CoreV1Api client for the cluster named in `config['cluster_name']`,
    authenticated via the assumed role's STS credentials (standard EKS auth: IAM
    identity -> presigned-STS bearer token -> k8s API) — no static kubeconfig file
    needed, so cross-account/cross-cluster access works purely from `integration_scope`
    config. Falls back to `config['kubeconfig_path']` (the original local/dev path)
    when no `cluster_name` is set, so existing local setups keep working unchanged.
    """
    from kubernetes import client as k8s_client

    cluster_name = config.get("cluster_name")
    if not cluster_name:
        return _k8s_client_from_static_kubeconfig(config)

    region = config.get("region") or default_region
    session = get_aws_session(config, default_region=region)
    eks = session.client("eks", region_name=region or None)
    cluster = eks.describe_cluster(name=cluster_name)["cluster"]
    endpoint = cluster["endpoint"]
    ca_data = cluster["certificateAuthority"]["data"]
    token = get_eks_bearer_token(session, cluster_name, region)

    configuration = k8s_client.Configuration()
    configuration.host = endpoint
    configuration.ssl_ca_cert = _ca_cert_path(endpoint, ca_data)
    configuration.api_key = {"authorization": token}
    configuration.api_key_prefix = {"authorization": "Bearer"}
    return k8s_client.CoreV1Api(k8s_client.ApiClient(configuration))


def _k8s_client_from_static_kubeconfig(config: dict):
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config

    kubeconfig_path = config.get("kubeconfig_path")
    if kubeconfig_path:
        k8s_config.load_kube_config(config_file=kubeconfig_path)
    else:
        k8s_config.load_incluster_config()
    return k8s_client.CoreV1Api()
