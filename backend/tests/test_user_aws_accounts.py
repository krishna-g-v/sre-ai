"""Unit tests for app/services/user_aws_accounts.py and the settings.UserAwsAccountCreate
validator — docs/10-nl-to-cli-execution.md §9.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.settings import UserAwsAccountCreate, UserAwsAccountOut


def test_accepts_a_well_formed_role_arn():
    account = UserAwsAccountCreate(
        label="nonprod",
        account_id="111111111111",
        role_arn="arn:aws:iam::111111111111:role/sre-agent-readonly",
        region="us-east-1",
    )
    assert account.label == "nonprod"


@pytest.mark.parametrize(
    "role_arn",
    [
        "not-an-arn",
        "arn:aws:iam::111111111111:user/someone",  # a user ARN, not a role
        "arn:aws:s3:::my-bucket",
        "",
    ],
)
def test_rejects_malformed_role_arns(role_arn):
    with pytest.raises(ValidationError):
        UserAwsAccountCreate(label="nonprod", role_arn=role_arn)


def test_rejects_blank_label():
    with pytest.raises(ValidationError):
        UserAwsAccountCreate(label="   ", role_arn="arn:aws:iam::111111111111:role/ro")


def test_strips_whitespace_from_label():
    account = UserAwsAccountCreate(
        label="  nonprod  ", role_arn="arn:aws:iam::111111111111:role/ro"
    )
    assert account.label == "nonprod"


def test_accepts_matching_access_key_and_secret_pair():
    account = UserAwsAccountCreate(
        label="nonprod",
        role_arn="arn:aws:iam::111111111111:role/ro",
        access_key_id="AKIAEXAMPLE",
        secret_access_key="s3cret",
    )
    assert account.access_key_id == "AKIAEXAMPLE"


def test_accepts_neither_access_key_nor_secret():
    account = UserAwsAccountCreate(
        label="nonprod", role_arn="arn:aws:iam::111111111111:role/ro"
    )
    assert account.access_key_id == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"access_key_id": "AKIAEXAMPLE"},  # key without secret
        {"secret_access_key": "s3cret"},  # secret without key
    ],
)
def test_rejects_one_sided_credential_pair(kwargs):
    with pytest.raises(ValidationError):
        UserAwsAccountCreate(
            label="nonprod", role_arn="arn:aws:iam::111111111111:role/ro", **kwargs
        )


def test_out_schema_never_exposes_the_secret():
    account = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000000",
        label="nonprod",
        account_id="111111111111",
        role_arn="arn:aws:iam::111111111111:role/ro",
        external_id="",
        region="us-east-1",
        access_key_id="AKIAEXAMPLE",
        secret_access_key="this-must-never-leave-the-server",
    )
    out = UserAwsAccountOut.from_model(account)

    assert out.has_own_credentials is True
    assert "secret_access_key" not in out.model_dump()
    assert "this-must-never-leave-the-server" not in out.model_dump_json()


def test_out_schema_has_own_credentials_false_when_unset():
    account = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000000",
        label="nonprod",
        account_id="111111111111",
        role_arn="arn:aws:iam::111111111111:role/ro",
        external_id="",
        region="us-east-1",
        access_key_id="",
        secret_access_key="",
    )
    out = UserAwsAccountOut.from_model(account)

    assert out.has_own_credentials is False
