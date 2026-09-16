"""Execute validated read-only aws/kubectl commands — docs/10-nl-to-cli-execution.md §3,
§5, §9.

Every command reaching this module has already passed `cli_validator.parse_and_validate`
— this module's job is safe execution, not policy. AWS access is resolved from the
*requesting user's own* registered accounts (`user_aws_accounts`, docs/10 §9), not the
admin-provisioned `IntegrationScope` model those hand-written tools in
app/agents/live_ops_agents.py still use — a user only ever reaches an account they
personally registered via the Settings page.

Three things happen for every command:

1. Any target/credential-overriding flag the generated text included (`--profile`,
   `--region`, `--kubeconfig`, `--context`, ...) is stripped and replaced with the
   trusted value from the resolved `UserAwsAccount` row — the generated command never
   controls which account/cluster it actually talks to.
2. Credentials are per-request and ephemeral: an AWS env dict built fresh from
   `aws_session.get_aws_session`, and for kubectl a temp kubeconfig file written per
   call and deleted in a `finally` — never a shared `~/.aws`/`~/.kube/config` (the
   backend serves multiple users/accounts concurrently from one process).
3. `subprocess.run` with `shell=False` and an explicit argv list — the string that was
   validated is never handed to a shell.
"""

import os
import subprocess
import tempfile
import uuid

import boto3
import yaml
from sqlalchemy.orm import Session

from app.db.models import UserAwsAccount
from app.services import aws_session
from app.services.cli_validator import (
    CommandRejected,
    ParsedAwsCommand,
    ParsedKubectlCommand,
    parse_and_validate,
)
from app.services.user_aws_accounts import account_config, accounts_for, resolve_account

_COMMAND_TIMEOUT_SECONDS = 20
_OUTPUT_CHAR_LIMIT = 8000

# Downstream of the validator's verb allowlist: these flags don't change *what* is being
# asked for, only *where*/*as whom* — the generated command must never control them.
_AWS_STRIPPED_FLAGS = {"--region", "--profile", "--endpoint-url", "--ca-bundle"}
_KUBECTL_STRIPPED_FLAGS = {
    "--kubeconfig",
    "--context",
    "--token",
    "--server",
    "--certificate-authority",
    "--client-certificate",
    "--client-key",
    "--as",
    "--as-group",
    "--insecure-skip-tls-verify",
}

NOT_CONFIGURED_MSG = "You don't have any AWS accounts registered yet — add one under Settings → AWS Accounts."


def _resolve_session(account: UserAwsAccount, region: str) -> "boto3.Session | str":
    """The assumed-role session for `account`, or an error string to return directly.

    `aws_session.get_aws_session` calls `sts.assume_role` with no try/except of its own
    (it's a shared low-level helper — other callers may want the raw exception). This is
    the boundary where that changes: an AssumeRole failure (wrong/missing trust policy,
    revoked credentials, IAM propagation delay, ...) is routine here — a user can easily
    register a role before its trust policy is fully set up — and must become a normal
    "ERROR: ..." chat answer, never an unhandled exception that crashes the request with
    a 500. Found by hitting exactly this against a real account: a real AccessDenied on
    sts:AssumeRole propagated all the way up through FastAPI uncaught."""
    try:
        return aws_session.get_aws_session(
            account_config(account), default_region=region
        )
    except Exception as exc:  # pragma: no cover - depends on real AWS/network behavior
        return f"[{account.label}] ERROR: could not assume {account.role_arn}: {exc}"


def _strip_flags(args: list[str], flags: set[str]) -> list[str]:
    """Remove `--flag value` and `--flag=value` pairs for any flag in `flags`."""
    cleaned: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        bare = token.split("=", 1)[0]
        if bare in flags:
            if "=" not in token:
                skip_next = True
            continue
        cleaned.append(token)
    return cleaned


TRUNCATION_MARKER = (
    "[truncated,"  # a deliberate, checkable sentinel — see cli_agent.py's retry loop
)


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CHAR_LIMIT:
        return text
    return (
        text[:_OUTPUT_CHAR_LIMIT]
        + f"\n... {TRUNCATION_MARKER} {len(text) - _OUTPUT_CHAR_LIMIT} more characters]"
    )


def _run(argv: list[str], *, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return f"ERROR: '{argv[0]}' is not installed in this environment — cannot execute live commands here yet."
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {_COMMAND_TIMEOUT_SECONDS}s."

    if result.returncode == 0:
        return _truncate(result.stdout) or "(command returned no output)"
    # "ERROR: " prefix is a deliberate, checkable sentinel — app/agents/cli_agent.py's
    # retry loop looks for it to decide whether to feed this back to the LLM for a
    # corrected command, rather than fragile substring-matching on arbitrary CLI text.
    return "ERROR: " + _truncate(f"{result.stdout}\n{result.stderr}".strip())


def run_readonly_aws(
    db: Session,
    user_id: uuid.UUID,
    command: str,
    *,
    account_label: str | None = None,
    default_region: str = "",
) -> str:
    """Validate and run an aws CLI command against exactly one of the requesting user's
    own registered accounts (docs/10 §9). Returns CommandRejected's/`user_aws_accounts.resolve_account`'s
    message directly (as a string) rather than raising, so callers (the generate/retry
    loop in app/agents/cli_agent.py) can feed it straight back to the LLM as the error
    to correct, same as any other execution failure."""
    try:
        parsed = parse_and_validate(command)
    except CommandRejected as exc:
        return f"Rejected: {exc}"
    if not isinstance(parsed, ParsedAwsCommand):
        return "Rejected: not an aws command."

    accounts = accounts_for(db, user_id)
    if not accounts:
        return NOT_CONFIGURED_MSG

    resolved = resolve_account(accounts, account_label)
    if isinstance(resolved, str):
        return resolved
    account = resolved

    base_args = _strip_flags(parsed.argv[1:], _AWS_STRIPPED_FLAGS)
    if "--output" not in " ".join(base_args):
        base_args += ["--output", "json"]

    region = account.region or default_region
    session = _resolve_session(account, region)
    if isinstance(session, str):
        return session
    creds = session.get_credentials().get_frozen_credentials()
    env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": creds.access_key,
        "AWS_SECRET_ACCESS_KEY": creds.secret_key,
        "AWS_DEFAULT_REGION": region or "",
    }
    if creds.token:
        env["AWS_SESSION_TOKEN"] = creds.token

    argv = ["aws", *base_args, "--region", region] if region else ["aws", *base_args]
    return f"[{account.label}]\n{_run(argv, env=env)}"


def _write_temp_kubeconfig(
    *, cluster_name: str, endpoint: str, ca_data_b64: str, token: str
) -> str:
    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": cluster_name,
                "cluster": {
                    "server": endpoint,
                    "certificate-authority-data": ca_data_b64,
                },
            }
        ],
        "users": [{"name": cluster_name, "user": {"token": token}}],
        "contexts": [
            {
                "name": cluster_name,
                "context": {"cluster": cluster_name, "user": cluster_name},
            }
        ],
        "current-context": cluster_name,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(kubeconfig, f)
        return f.name


def run_readonly_kubectl(
    db: Session,
    user_id: uuid.UUID,
    command: str,
    *,
    account_label: str | None = None,
    cluster_name: str | None = None,
    default_region: str = "",
) -> str:
    """Validate and run a kubectl command against `cluster_name` inside exactly one of
    the requesting user's own registered accounts (docs/10 §9). Unlike the old group-
    scoped design, cluster names aren't pre-registered anywhere — accounts are the only
    thing a user configures — so `cluster_name` is always required here; the caller
    (app/agents/cli_agent.py) resolves it from the current question or from an earlier
    turn's `aws eks list-clusters` output in conversation history, never invents one."""
    try:
        parsed = parse_and_validate(command)
    except CommandRejected as exc:
        return f"Rejected: {exc}"
    if not isinstance(parsed, ParsedKubectlCommand):
        return "Rejected: not a kubectl command."

    accounts = accounts_for(db, user_id)
    if not accounts:
        return NOT_CONFIGURED_MSG

    resolved = resolve_account(accounts, account_label)
    if isinstance(resolved, str):
        return resolved
    account = resolved

    if not cluster_name:
        return "Rejected: which EKS cluster? Specify cluster_name (e.g. from an earlier 'list clusters' command)."

    region = account.region or default_region
    session = _resolve_session(account, region)
    if isinstance(session, str):
        return session
    eks = session.client("eks", region_name=region or None)
    try:
        cluster = eks.describe_cluster(name=cluster_name)["cluster"]
    except (
        Exception
    ) as exc:  # pragma: no cover - depends on external cluster/credentials
        return f"[{account.label}] ERROR: could not describe cluster '{cluster_name}': {exc}"

    token = aws_session.get_eks_bearer_token(session, cluster_name, region)
    kubeconfig_path = _write_temp_kubeconfig(
        cluster_name=cluster_name,
        endpoint=cluster["endpoint"],
        ca_data_b64=cluster["certificateAuthority"]["data"],
        token=token,
    )
    base_args = _strip_flags(parsed.argv[1:], _KUBECTL_STRIPPED_FLAGS)
    if parsed.verb == "logs" and "--tail" not in " ".join(base_args):
        base_args += ["--tail", "200"]
    try:
        argv = ["kubectl", "--kubeconfig", kubeconfig_path, *base_args]
        return f"[{account.label}/{cluster_name}]\n{_run(argv)}"
    finally:
        os.unlink(kubeconfig_path)
