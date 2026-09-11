"""Read-only command validator — docs/10-nl-to-cli-execution.md §3-§4.

A deterministic, allowlist-based gate, not a prompt instruction: this is what stands
between an LLM-generated `aws`/`kubectl` command string and actually running it. Every
generated command must pass through `parse_and_validate` before `cli_executor.py` runs
anything — nothing here trusts the LLM to only ask for reads.

Two independent things happen: (1) reject anything not shaped like a plain, single
`aws`/`kubectl` invocation, and (2) reject any verb/operation not on the explicit
read-only allowlist per service. Account/cluster/region scoping and any target-
overriding flags (`--profile`, `--kubeconfig`, ...) are handled downstream in
`cli_executor.py`, not here — this module only ever answers "is this shape of command
allowed at all," never "is it allowed for this particular user."
"""

import shlex
from dataclasses import dataclass

# Only these two binaries are ever runnable — no shell, no path resolution tricks
# (argv[0] is compared exactly, never resolved via $PATH by a shell).
ALLOWED_BINARIES = ("aws", "kubectl")

# A single generated string must parse into one plain command — none of these should be
# reachable through shlex.split into a single argv list, but checked defensively anyway
# in case a future change routes raw text here some other way.
_SUSPICIOUS_SUBSTRINGS = ("&&", "||", "|", ";", "`", "$(", "\n")

ALLOWED_AWS_SERVICES = {"eks", "ec2", "elbv2", "ecr", "cloudwatch", "logs", "rds"}

# describe-*/list-*/get-* is the read-only shape for nearly all AWS APIs; the extras
# below are the handful of genuinely-read operations that don't happen to start with
# one of those three words.
_ALLOWED_OPERATION_PREFIXES = ("describe-", "list-", "get-")
_SERVICE_EXTRA_ALLOWED_OPERATIONS: dict[str, set[str]] = {
    "logs": {"filter-log-events", "start-query", "stop-query"},
}

# docs/10 §4 — technically read operations, but they return actual sensitive payloads
# (image layer bytes, DB log contents) rather than metadata, so they're excluded even
# though their names would otherwise match the allowed prefixes above.
_SERVICE_DENYLISTED_OPERATIONS: dict[str, set[str]] = {
    "ecr": {"get-download-url-for-layer", "batch-get-image"},
    "rds": {"download-db-log-file-portion", "download-db-log-file-portion-batch"},
}

ALLOWED_KUBECTL_VERBS = {
    "get",
    "describe",
    "logs",
    "top",
    "explain",
    "api-resources",
    "version",
}


class CommandRejected(Exception):
    """Raised for any command that fails the read-only allowlist — always caught by the
    caller and turned into a user-facing explanation, never allowed to propagate as a
    generic error that might look like an execution failure instead of a policy one."""


@dataclass
class ParsedAwsCommand:
    binary: str  # always "aws"
    service: str
    operation: str
    argv: list[str]  # the full, original argv (argv[0] == "aws")


@dataclass
class ParsedKubectlCommand:
    binary: str  # always "kubectl"
    verb: str
    argv: list[str]  # the full, original argv (argv[0] == "kubectl")


def _reject_if_suspicious(command: str) -> None:
    for token in _SUSPICIOUS_SUBSTRINGS:
        if token in command:
            raise CommandRejected(
                f"Command contains a disallowed character sequence: {token!r}"
            )


def parse_and_validate(command: str) -> ParsedAwsCommand | ParsedKubectlCommand:
    """Parse a generated command string and check it against the read-only allowlist.
    Raises CommandRejected with a human-readable reason on any failure — never returns
    a partially-valid result."""
    _reject_if_suspicious(command)

    try:
        argv = shlex.split(command)
    except ValueError as exc:  # unbalanced quotes, etc.
        raise CommandRejected(f"Could not parse command: {exc}") from exc

    if not argv:
        raise CommandRejected("Empty command.")

    binary = argv[0]
    if binary not in ALLOWED_BINARIES:
        raise CommandRejected(
            f"'{binary}' is not an allowed binary — only {ALLOWED_BINARIES} may be executed."
        )

    if binary == "aws":
        return _validate_aws(argv)
    return _validate_kubectl(argv)


def _validate_aws(argv: list[str]) -> ParsedAwsCommand:
    if len(argv) < 3:
        raise CommandRejected(
            "An aws command needs at least a service and an operation."
        )

    service, operation = argv[1], argv[2]
    if service not in ALLOWED_AWS_SERVICES:
        raise CommandRejected(
            f"aws service '{service}' is not in the allowed read-only scope {sorted(ALLOWED_AWS_SERVICES)}."
        )

    if operation in _SERVICE_DENYLISTED_OPERATIONS.get(service, set()):
        raise CommandRejected(
            f"'aws {service} {operation}' is explicitly excluded (returns sensitive data, not metadata)."
        )

    is_prefixed_read = operation.startswith(_ALLOWED_OPERATION_PREFIXES)
    is_extra_allowed = operation in _SERVICE_EXTRA_ALLOWED_OPERATIONS.get(
        service, set()
    )
    if not (is_prefixed_read or is_extra_allowed):
        raise CommandRejected(
            f"'aws {service} {operation}' is not a recognized read-only operation "
            f"(expected one starting with describe-/list-/get-, or an explicitly allowed extra)."
        )

    return ParsedAwsCommand(
        binary="aws", service=service, operation=operation, argv=argv
    )


def _validate_kubectl(argv: list[str]) -> ParsedKubectlCommand:
    if len(argv) < 2:
        raise CommandRejected("A kubectl command needs at least a verb.")

    verb = argv[1]
    if verb not in ALLOWED_KUBECTL_VERBS:
        raise CommandRejected(
            f"kubectl verb '{verb}' is not in the allowed read-only set {sorted(ALLOWED_KUBECTL_VERBS)}."
        )

    return ParsedKubectlCommand(binary="kubectl", verb=verb, argv=argv)
