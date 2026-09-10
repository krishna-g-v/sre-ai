import logging
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("sre_ai.config")

_DEFAULT_JWT_SECRET = "dev-only-insecure-secret-change-me"
_DEFAULT_BOOTSTRAP_PASSWORD = "admin"
_DEFAULT_DATABASE_URL = "postgresql+psycopg://sreagent:sreagent@localhost:5432/sreagent"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM (chat/completions) ---
    # Generic contract (docs/06-deployment-and-environments.md §2): dev uses an
    # OpenAI-compatible endpoint (nscale), prod uses AWS Bedrock. llm_provider defaults
    # to openai_compatible but auto-switches to bedrock below if BEDROCK_* vars are
    # present and llm_provider wasn't explicitly set — this lets the AWS/EKS Helm
    # deployment (which sets BEDROCK_MODEL/BEDROCK_INFERENCE_PROFILE_ARN/BEDROCK_REGION,
    # not LLM_PROVIDER) work without needing its own values.yaml changed.
    llm_provider: Literal["openai_compatible", "bedrock"] = "openai_compatible"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
    llm_region: str = ""

    # --- Bedrock-specific (AWS/EKS deployment) ---
    # bedrock_inference_profile_arn, when set, is used as the Bedrock `modelId` — that's
    # how AWS Bedrock application inference profiles work (the profile ARN *is* the model
    # identifier passed to Converse/InvokeModel), not the bare model name.
    bedrock_model: str = ""
    bedrock_inference_profile_arn: str = ""
    bedrock_region: str = ""

    # --- Embeddings (local model, baked into the image at build time) ---
    embedding_provider: Literal["local"] = "local"
    embedding_model_id: str = "BAAI/bge-large-en-v1.5"
    embedding_local_model_path: str = "/opt/models/bge-large-en-v1.5"
    embedding_dim: int = 1024

    # --- Database ---
    # Either set DATABASE_URL directly (local/docker-compose dev), or set the discrete
    # DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD/DB_SSLMODE parts (AWS/EKS Helm chart,
    # which injects the password via envFrom a Secret) and let the validator below build
    # the URL — matches how the RDS connection is actually configured in that chart.
    database_url: str = _DEFAULT_DATABASE_URL
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "sreagent"
    db_user: str = "sreagent"
    # The `sre-ai-db` Secret's key is `password`, not `DB_PASSWORD` — envFrom turns
    # secret keys into identically-named env vars, so accept both spellings rather
    # than depending on the secret being renamed to match.
    db_password: str = Field(default="", validation_alias=AliasChoices("DB_PASSWORD", "password"))
    db_sslmode: str = ""

    # --- Auth ---
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_expiry_minutes: int = 1440
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = _DEFAULT_BOOTSTRAP_PASSWORD

    # --- Integrations ---
    aws_region: str = ""
    kubeconfig_path: str = ""
    grafana_base_url: str = ""
    grafana_api_key: str = ""
    prometheus_base_url: str = ""
    alertmanager_base_url: str = ""

    # --- CORS (dev convenience) ---
    # Not needed in the AWS/EKS deployment — the frontend's own server proxies /api/*
    # to the backend Service, so the browser never makes a cross-origin request. Only
    # matters for local dev, where the browser talks to the backend's port directly.
    cors_allow_origins: str = "http://localhost:5173"

    # --- Session pinning tuning (see docs/08-chat-sessions-and-orchestration.md) ---
    dominant_match_margin: float = 0.08

    def model_post_init(self, __context: object) -> None:
        explicit = self.model_fields_set

        # Build DATABASE_URL from discrete DB_* parts if that's what was actually
        # provided (AWS/EKS path) rather than an explicit DATABASE_URL (dev path).
        if "database_url" not in explicit and self.db_host:
            url = f"postgresql+psycopg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
            if self.db_sslmode:
                url += f"?sslmode={self.db_sslmode}"
            self.database_url = url

        # Auto-select the Bedrock adapter when Bedrock-specific config is present and
        # nothing explicitly chose a provider — see the llm_provider docstring above.
        if "llm_provider" not in explicit and (self.bedrock_inference_profile_arn or self.bedrock_model):
            self.llm_provider = "bedrock"
            if "llm_model" not in explicit:
                self.llm_model = self.bedrock_inference_profile_arn or self.bedrock_model
            if "llm_region" not in explicit:
                self.llm_region = self.bedrock_region or self.aws_region

        # Loud, not silent: a "production" pod running with these defaults means anyone
        # who knows the public default can forge auth tokens / log in as admin.
        if self.jwt_secret == _DEFAULT_JWT_SECRET:
            logger.warning(
                "JWT_SECRET is unset — using the insecure built-in default. "
                "Set a real JWT_SECRET for any environment other than local dev."
            )
        if self.bootstrap_admin_password == _DEFAULT_BOOTSTRAP_PASSWORD:
            logger.warning(
                "BOOTSTRAP_ADMIN_PASSWORD is unset — the bootstrap admin account will be "
                "created with the default 'admin' password. Set a real one and rotate it "
                "immediately after first login for any environment other than local dev."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
