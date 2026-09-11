"""Unit tests for app/services/cli_executor.py — docs/10-nl-to-cli-execution.md §3, §5, §9.

No real subprocess/AWS/k8s calls: subprocess.run, aws_session, and accounts_for are all
mocked, so these run offline and fast.
"""

import os
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import cli_executor
from app.services.cli_executor import (
    _strip_flags,
    run_readonly_aws,
    run_readonly_kubectl,
)


def _account(label="nonprod", **extra):
    defaults = {
        "label": label,
        "account_id": "111111111111",
        "role_arn": "arn:aws:iam::111111111111:role/ro",
        "external_id": "",
        "region": "us-east-1",
        "access_key_id": "",
        "secret_access_key": "",
    }
    defaults.update(extra)
    return SimpleNamespace(**defaults)


def _frozen_creds(token="session-token"):
    return SimpleNamespace(access_key="AKIA...", secret_key="secret", token=token)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_strip_flags_handles_space_and_equals_forms():
    args = ["--region", "us-east-1", "--profile=dev", "--name", "prod"]
    cleaned = _strip_flags(args, {"--region", "--profile"})
    assert cleaned == ["--name", "prod"]


def test_run_readonly_aws_rejects_write_command_without_touching_accounts():
    with patch("app.services.cli_executor.accounts_for") as mock_accounts:
        result = run_readonly_aws(
            MagicMock(), MagicMock(), "aws ec2 terminate-instances --instance-ids i-123"
        )

    assert result.startswith("Rejected:")
    mock_accounts.assert_not_called()


def test_run_readonly_aws_reports_not_configured_when_no_accounts_registered():
    with patch("app.services.cli_executor.accounts_for", return_value=[]):
        result = run_readonly_aws(
            MagicMock(), MagicMock(), "aws eks describe-cluster --name prod"
        )

    assert result == cli_executor.NOT_CONFIGURED_MSG


def test_run_readonly_aws_injects_trusted_region_and_strips_generated_one():
    account = _account()
    mock_session = MagicMock()
    mock_session.get_credentials.return_value.get_frozen_credentials.return_value = (
        _frozen_creds()
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch(
            "app.services.cli_executor.subprocess.run",
            return_value=_completed(stdout="{}"),
        ) as mock_run,
    ):
        result = run_readonly_aws(
            MagicMock(),
            MagicMock(),
            "aws eks describe-cluster --name prod --region us-west-2 --profile evil",
        )

    argv = mock_run.call_args.args[0]
    assert argv[0] == "aws"
    assert "--profile" not in argv
    assert argv.count("--region") == 1
    assert argv[argv.index("--region") + 1] == "us-east-1"
    assert "[nonprod]" in result


def test_run_readonly_aws_sets_session_token_env_when_present():
    account = _account()
    mock_session = MagicMock()
    mock_session.get_credentials.return_value.get_frozen_credentials.return_value = (
        _frozen_creds(token="tok-123")
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch(
            "app.services.cli_executor.subprocess.run",
            return_value=_completed(stdout="{}"),
        ) as mock_run,
    ):
        run_readonly_aws(
            MagicMock(), MagicMock(), "aws eks describe-cluster --name prod"
        )

    env = mock_run.call_args.kwargs["env"]
    assert env["AWS_ACCESS_KEY_ID"] == "AKIA..."
    assert env["AWS_SESSION_TOKEN"] == "tok-123"
    assert env["AWS_DEFAULT_REGION"] == "us-east-1"


def test_run_readonly_aws_marks_nonzero_exit_as_error():
    account = _account()
    mock_session = MagicMock()
    mock_session.get_credentials.return_value.get_frozen_credentials.return_value = (
        _frozen_creds()
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch(
            "app.services.cli_executor.subprocess.run",
            return_value=_completed(stderr="ResourceNotFoundException", returncode=254),
        ),
    ):
        result = run_readonly_aws(
            MagicMock(), MagicMock(), "aws eks describe-cluster --name missing"
        )

    assert "ERROR:" in result
    assert "ResourceNotFoundException" in result


def test_run_readonly_aws_reports_missing_binary_cleanly():
    account = _account()
    mock_session = MagicMock()
    mock_session.get_credentials.return_value.get_frozen_credentials.return_value = (
        _frozen_creds()
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch(
            "app.services.cli_executor.subprocess.run", side_effect=FileNotFoundError()
        ),
    ):
        result = run_readonly_aws(
            MagicMock(), MagicMock(), "aws eks describe-cluster --name prod"
        )

    assert "ERROR:" in result
    assert "not installed" in result


def test_run_readonly_aws_turns_assume_role_failure_into_a_clean_error_not_a_crash():
    """Regression test for a real AccessDenied hit against a real account during
    testing — sts.assume_role failing (bad/missing trust policy, revoked creds, ...) is
    routine, not exceptional, and must never propagate as an unhandled exception."""
    from botocore.exceptions import ClientError

    account = _account()
    denied = ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
                "Message": "User: ... is not authorized to perform: sts:AssumeRole",
            }
        },
        "AssumeRole",
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", side_effect=denied),
        patch("app.services.cli_executor.subprocess.run") as mock_run,
    ):
        result = run_readonly_aws(
            MagicMock(), MagicMock(), "aws eks describe-cluster --name prod"
        )

    assert "ERROR:" in result
    assert "AccessDenied" in result
    mock_run.assert_not_called()  # never got as far as actually running the CLI


def test_run_readonly_kubectl_turns_assume_role_failure_into_a_clean_error_not_a_crash():
    from botocore.exceptions import ClientError

    account = _account(cluster_name="nonprod-a")
    denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "AssumeRole"
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", side_effect=denied),
        patch("app.services.cli_executor.subprocess.run") as mock_run,
    ):
        result = run_readonly_kubectl(
            MagicMock(),
            MagicMock(),
            "kubectl get pods -n payments",
            cluster_name="nonprod-a",
        )

    assert "ERROR:" in result
    assert "AccessDenied" in result
    mock_run.assert_not_called()


def test_run_readonly_aws_asks_for_disambiguation_with_multiple_accounts_and_no_label():
    accounts = [_account("nonprod"), _account("prod")]

    with (
        patch("app.services.cli_executor.accounts_for", return_value=accounts),
        patch("app.services.cli_executor.subprocess.run") as mock_run,
    ):
        result = run_readonly_aws(MagicMock(), MagicMock(), "aws eks list-clusters")

    assert "nonprod" in result
    assert "prod" in result
    assert "Multiple" in result
    mock_run.assert_not_called()


def test_run_readonly_aws_targets_only_the_named_account():
    accounts = [_account("nonprod"), _account("prod")]
    mock_session = MagicMock()
    mock_session.get_credentials.return_value.get_frozen_credentials.return_value = (
        _frozen_creds()
    )

    with (
        patch("app.services.cli_executor.accounts_for", return_value=accounts),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch(
            "app.services.cli_executor.subprocess.run",
            return_value=_completed(stdout="[]"),
        ) as mock_run,
    ):
        result = run_readonly_aws(
            MagicMock(), MagicMock(), "aws eks list-clusters", account_label="prod"
        )

    assert mock_run.call_count == 1
    assert "[prod]" in result
    assert "nonprod" not in result


def test_run_readonly_aws_rejects_unknown_account_label():
    accounts = [_account("nonprod")]

    with (
        patch("app.services.cli_executor.accounts_for", return_value=accounts),
        patch("app.services.cli_executor.subprocess.run") as mock_run,
    ):
        result = run_readonly_aws(
            MagicMock(),
            MagicMock(),
            "aws eks list-clusters",
            account_label="does-not-exist",
        )

    assert result.startswith("Rejected:")
    assert "does-not-exist" in result
    mock_run.assert_not_called()


def test_run_readonly_kubectl_rejects_write_command_without_touching_accounts():
    with patch("app.services.cli_executor.accounts_for") as mock_accounts:
        result = run_readonly_kubectl(
            MagicMock(), MagicMock(), "kubectl delete pod x -n payments"
        )

    assert result.startswith("Rejected:")
    mock_accounts.assert_not_called()


def test_run_readonly_kubectl_requires_cluster_name():
    account = _account()

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.cli_executor.subprocess.run") as mock_run,
    ):
        result = run_readonly_kubectl(
            MagicMock(), MagicMock(), "kubectl get pods -n payments"
        )

    assert result.startswith("Rejected:")
    assert "cluster" in result.lower()
    mock_run.assert_not_called()


def test_run_readonly_kubectl_writes_and_deletes_ephemeral_kubeconfig():
    account = _account()
    mock_session = MagicMock()
    mock_session.client.return_value.describe_cluster.return_value = {
        "cluster": {
            "endpoint": "https://example.com",
            "certificateAuthority": {"data": "ZmFrZS1jYQ=="},
        }
    }

    captured_paths: list[str] = []

    def fake_run(argv, **kwargs):
        idx = argv.index("--kubeconfig")
        path = argv[idx + 1]
        captured_paths.append(path)
        assert os.path.exists(path)
        return _completed(stdout="pod list")

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch(
            "app.services.aws_session.get_eks_bearer_token",
            return_value="k8s-aws-v1.faketoken",
        ),
        patch("app.services.cli_executor.subprocess.run", side_effect=fake_run),
    ):
        result = run_readonly_kubectl(
            MagicMock(),
            MagicMock(),
            "kubectl get pods -n payments",
            cluster_name="nonprod-a",
        )

    assert "[nonprod/nonprod-a]" in result
    assert "pod list" in result
    assert len(captured_paths) == 1
    assert not os.path.exists(captured_paths[0])  # deleted after the call


def test_run_readonly_kubectl_injects_default_tail_for_logs():
    account = _account()
    mock_session = MagicMock()
    mock_session.client.return_value.describe_cluster.return_value = {
        "cluster": {
            "endpoint": "https://example.com",
            "certificateAuthority": {"data": "ZmFrZS1jYQ=="},
        }
    }

    with (
        patch("app.services.cli_executor.accounts_for", return_value=[account]),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch("app.services.aws_session.get_eks_bearer_token", return_value="tok"),
        patch(
            "app.services.cli_executor.subprocess.run",
            return_value=_completed(stdout="log lines"),
        ) as mock_run,
    ):
        run_readonly_kubectl(
            MagicMock(),
            MagicMock(),
            "kubectl logs my-pod -n payments",
            cluster_name="nonprod-a",
        )

    argv = mock_run.call_args.args[0]
    assert "--tail" in argv
    assert argv[argv.index("--tail") + 1] == "200"


def test_run_readonly_kubectl_asks_for_disambiguation_with_multiple_accounts_and_no_label():
    accounts = [_account("nonprod"), _account("prod")]

    with (
        patch("app.services.cli_executor.accounts_for", return_value=accounts),
        patch("app.services.cli_executor.subprocess.run") as mock_run,
    ):
        result = run_readonly_kubectl(
            MagicMock(),
            MagicMock(),
            "kubectl get pods -n payments",
            cluster_name="nonprod-a",
        )

    assert "Multiple" in result
    mock_run.assert_not_called()


def test_run_readonly_kubectl_targets_only_the_named_account_and_cluster():
    accounts = [_account("nonprod"), _account("prod")]
    mock_session = MagicMock()
    mock_session.client.return_value.describe_cluster.return_value = {
        "cluster": {
            "endpoint": "https://example.com",
            "certificateAuthority": {"data": "ZmFrZS1jYQ=="},
        }
    }

    with (
        patch("app.services.cli_executor.accounts_for", return_value=accounts),
        patch("app.services.aws_session.get_aws_session", return_value=mock_session),
        patch("app.services.aws_session.get_eks_bearer_token", return_value="tok"),
        patch(
            "app.services.cli_executor.subprocess.run",
            return_value=_completed(stdout="pod list"),
        ) as mock_run,
    ):
        result = run_readonly_kubectl(
            MagicMock(),
            MagicMock(),
            "kubectl get pods -n payments",
            account_label="nonprod",
            cluster_name="nonprod-a",
        )

    assert mock_run.call_count == 1
    assert "[nonprod/nonprod-a]" in result
