from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


class UserAwsAccountOut(BaseModel):
    id: UUID
    label: str
    account_id: str
    role_arn: str
    external_id: str
    region: str
    has_own_credentials: (
        bool  # never the secret itself — see UserAwsAccount's docstring
    )

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, account) -> "UserAwsAccountOut":
        return cls(
            id=account.id,
            label=account.label,
            account_id=account.account_id,
            role_arn=account.role_arn,
            external_id=account.external_id,
            region=account.region,
            has_own_credentials=bool(account.access_key_id),
        )


class UserAwsAccountCreate(BaseModel):
    label: str
    account_id: str = ""
    role_arn: str
    external_id: str = ""
    region: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label cannot be empty")
        return v

    @field_validator("role_arn")
    @classmethod
    def _role_arn_looks_valid(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("arn:aws:iam::") or ":role/" not in v:
            raise ValueError(
                "role_arn must look like arn:aws:iam::<account_id>:role/<name>"
            )
        return v

    @model_validator(mode="after")
    def _credentials_come_as_a_pair(self) -> "UserAwsAccountCreate":
        if bool(self.access_key_id.strip()) != bool(self.secret_access_key.strip()):
            raise ValueError(
                "access_key_id and secret_access_key must be provided together, or not at all"
            )
        return self


class UserAwsAccountUpdate(BaseModel):
    """All fields optional — only supplied ones change. Used to add/rotate/clear
    access_key_id+secret_access_key on an account created before this field existed,
    without needing to delete and recreate it (which would also change its id)."""

    account_id: str | None = None
    role_arn: str | None = None
    external_id: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None

    @field_validator("role_arn")
    @classmethod
    def _role_arn_looks_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v.startswith("arn:aws:iam::") or ":role/" not in v:
            raise ValueError(
                "role_arn must look like arn:aws:iam::<account_id>:role/<name>"
            )
        return v
