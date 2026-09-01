from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nevo.ai_gateway.entities import ProviderRequest, ProviderResponse
from nevo.ai_gateway.errors import (
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from nevo.domain.ai_gateway.vocabulary import AiProviderName


class _ClaudeTextBlock(BaseModel):
    type: str
    text: str | None = None


class _ClaudeUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class _ClaudeResponse(BaseModel):
    content: list[_ClaudeTextBlock] = Field(default_factory=list)
    model: str | None = None
    usage: _ClaudeUsage = Field(default_factory=_ClaudeUsage)


class ClaudeRestProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        anthropic_version: str,
        timeout_seconds: float,
        prompt_caching_enabled: bool,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._anthropic_version = anthropic_version
        self._prompt_caching_enabled = prompt_caching_enabled
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        """Whether this provider has the credentials to be called at all."""
        return bool(self._api_key)

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self._api_key:
            raise ProviderNotConfiguredError

        payload: dict[str, Any] = {
            "model": request.model or self._model,
            "max_tokens": request.max_output_tokens,
            "system": [
                {
                    "type": "text",
                    "text": request.system_instruction,
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": request.user_content,
                        }
                    ],
                }
            ],
        }
        if self._prompt_caching_enabled and request.cache_prompt:
            payload["cache_control"] = {"type": "ephemeral"}
            payload["system"][0]["cache_control"] = {"type": "ephemeral"}

        try:
            response = await self._client.post(
                f"{self._base_url}/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": self._anthropic_version,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            parsed = _ClaudeResponse.model_validate(response.json())
        except (
            httpx.HTTPError,
            ValueError,
            ValidationError,
        ) as error:
            raise ProviderUnavailableError from error

        text = "".join(
            block.text or "" for block in parsed.content if block.type == "text"
        ).strip()
        if not text:
            raise ProviderResponseError
        return ProviderResponse(
            text=text,
            provider=AiProviderName.CLAUDE,
            model=parsed.model or request.model or self._model,
            input_tokens=parsed.usage.input_tokens,
            output_tokens=parsed.usage.output_tokens,
            cache_creation_input_tokens=parsed.usage.cache_creation_input_tokens,
            cache_read_input_tokens=parsed.usage.cache_read_input_tokens,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
