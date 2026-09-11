"""Unit tests for app/services/aws_session.py — docs/09-ops-runbook-and-proactive-monitoring.md §2.

No real AWS calls: boto3.client("sts") and boto3.Session are mocked, so these run
offline and fast (unlike tests/e2e, no live credentials or network needed).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from botocore.credentials import Credentials
from botocore.hooks import HierarchicalEmitter

from app.services import aws_session


def _fresh_caches():
    aws_session._session_cache.clear()
    aws_session._ca_file_cache.clear()


def test_get_aws_session_without_role_arn_uses_ambient_credentials():
    _fresh_caches()
    with patch("app.services.aws_session.boto3.Session") as mock_session_cls:
        aws_session.get_aws_session({"region": "us-east-1"})
        mock_session_cls.assert_called_once_with(region_name="us-east-1")


def test_get_aws_session_assumes_role_and_caches():
    _fresh_caches()
    fake_creds = {
        "AccessKeyId": "AKIA...",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": datetime.now(UTC) + timedelta(hours=1),
    }
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {"Credentials": fake_creds}

    with (
        patch(
            "app.services.aws_session.boto3.client", return_value=mock_sts
        ) as mock_client,
        patch("app.services.aws_session.boto3.Session") as mock_session_cls,
    ):
        config = {
            "role_arn": "arn:aws:iam::111111111111:role/sre-agent-readonly",
            "region": "us-east-1",
        }

        aws_session.get_aws_session(config)
        aws_session.get_aws_session(
            config
        )  # second call should hit the cache, not STS again

        mock_client.assert_called_once_with("sts", region_name="us-east-1")
        mock_sts.assume_role.assert_called_once_with(
            RoleArn="arn:aws:iam::111111111111:role/sre-agent-readonly",
            RoleSessionName="sre-agent",
        )
        assert mock_session_cls.call_count == 1


def test_get_aws_session_passes_external_id_when_set():
    _fresh_caches()
    fake_creds = {
        "AccessKeyId": "AKIA...",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": datetime.now(UTC) + timedelta(hours=1),
    }
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {"Credentials": fake_creds}

    with (
        patch("app.services.aws_session.boto3.client", return_value=mock_sts),
        patch("app.services.aws_session.boto3.Session"),
    ):
        config = {
            "role_arn": "arn:aws:iam::111111111111:role/sre-agent-readonly",
            "external_id": "corp-external-id",
            "region": "us-east-1",
        }
        aws_session.get_aws_session(config)

        mock_sts.assume_role.assert_called_once_with(
            RoleArn="arn:aws:iam::111111111111:role/sre-agent-readonly",
            RoleSessionName="sre-agent",
            ExternalId="corp-external-id",
        )


def test_get_aws_session_re_assumes_after_expiry():
    _fresh_caches()
    expired_creds = {
        "AccessKeyId": "AKIA...",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": datetime.now(UTC) - timedelta(minutes=1),
    }
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {"Credentials": expired_creds}

    with (
        patch("app.services.aws_session.boto3.client", return_value=mock_sts),
        patch("app.services.aws_session.boto3.Session"),
    ):
        config = {
            "role_arn": "arn:aws:iam::111111111111:role/sre-agent-readonly",
            "region": "us-east-1",
        }
        aws_session.get_aws_session(config)
        aws_session.get_aws_session(config)

        assert mock_sts.assume_role.call_count == 2


def test_get_eks_bearer_token_has_expected_prefix():
    # Real Credentials + a real event emitter (not MagicMocks) so botocore's actual
    # SigV4 signing path runs end to end against fake-but-well-formed values.
    mock_session = MagicMock()
    mock_session.get_credentials.return_value = Credentials(
        "AKIAEXAMPLE", "secretkey", "sessiontoken"
    )
    mock_session.events = HierarchicalEmitter()

    token = aws_session.get_eks_bearer_token(mock_session, "my-cluster", "us-east-1")

    assert token.startswith("k8s-aws-v1.")
    assert (
        "=" not in token
    )  # base64 padding must be stripped for the k8s auth webhook format


def test_get_aws_session_uses_per_account_base_credentials_when_given():
    """docs/10-nl-to-cli-execution.md §9 — a UserAwsAccount can supply its own base
    identity instead of the shared ambient one."""
    _fresh_caches()
    fake_creds = {
        "AccessKeyId": "AKIA...",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": datetime.now(UTC) + timedelta(hours=1),
    }
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {"Credentials": fake_creds}

    with (
        patch(
            "app.services.aws_session.boto3.client", return_value=mock_sts
        ) as mock_client,
        patch("app.services.aws_session.boto3.Session"),
    ):
        config = {
            "role_arn": "arn:aws:iam::111111111111:role/sre-agent-readonly",
            "region": "us-east-1",
            "access_key_id": "AKIAOWNKEY",
            "secret_access_key": "owns3cret",
        }
        aws_session.get_aws_session(config)

    mock_client.assert_called_once_with(
        "sts",
        region_name="us-east-1",
        aws_access_key_id="AKIAOWNKEY",
        aws_secret_access_key="owns3cret",
        aws_session_token=None,
    )


def test_get_aws_session_does_not_share_cache_across_different_base_identities():
    """The bug this guards: two different users' own credentials (or a user's own
    credentials vs. the shared ambient identity) assuming a same-named role string must
    never reuse each other's cached session — the cache key has to include *who* is
    doing the assuming, not just which role."""
    _fresh_caches()
    fake_creds = {
        "AccessKeyId": "AKIA...",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
        "Expiration": datetime.now(UTC) + timedelta(hours=1),
    }
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {"Credentials": fake_creds}

    with (
        patch(
            "app.services.aws_session.boto3.client", return_value=mock_sts
        ) as mock_client,
        patch("app.services.aws_session.boto3.Session"),
    ):
        same_role_config = {
            "role_arn": "arn:aws:iam::111111111111:role/sre-agent-readonly",
            "region": "us-east-1",
        }
        aws_session.get_aws_session(
            {
                **same_role_config,
                "access_key_id": "AKIAUSERONE",
                "secret_access_key": "x",
            }
        )
        aws_session.get_aws_session(
            {
                **same_role_config,
                "access_key_id": "AKIAUSERTWO",
                "secret_access_key": "y",
            }
        )
        aws_session.get_aws_session(
            same_role_config
        )  # ambient — third distinct identity

    # three distinct base identities -> three separate assume_role calls, none reused
    assert mock_sts.assume_role.call_count == 3
    assert mock_client.call_count == 3
