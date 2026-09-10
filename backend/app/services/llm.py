"""LLM adapter — docs/06-deployment-and-environments.md §2.

Two adapter *kinds*, never a hardcoded vendor name in application logic:
  - openai_compatible: works against any vendor exposing a /v1/chat/completions API
    (nscale in dev; would also work unmodified against OpenRouter or others).
  - bedrock: AWS SDK-based, for prod.
"""

from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import get_settings


class LLMAdapter(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str: ...


class OpenAICompatibleAdapter(LLMAdapter):
    def __init__(self, base_url: str, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


class BedrockAdapter(LLMAdapter):
    """Untested in this dev sandbox (no AWS credentials here) — wired per the documented
    contract for when this deploys to prod EKS with Bedrock access. See docs/06 §2."""

    def __init__(self, model_id: str, region: str):
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region)
        self._model_id = model_id

    def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        conversation = [m for m in messages if m["role"] != "system"]
        response = self._client.converse(
            modelId=self._model_id,
            system=[{"text": system}] if system else [],
            messages=[{"role": m["role"], "content": [{"text": m["content"]}]} for m in conversation],
            inferenceConfig={"temperature": temperature},
        )
        return response["output"]["message"]["content"][0]["text"]


@lru_cache
def get_llm() -> LLMAdapter:
    settings = get_settings()
    if settings.llm_provider == "bedrock":
        return BedrockAdapter(model_id=settings.llm_model, region=settings.llm_region)
    return OpenAICompatibleAdapter(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
