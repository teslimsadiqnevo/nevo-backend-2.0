from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nevo.ai_gateway.entities import ProviderRequest, ProviderResponse, ToolCall
from nevo.ai_gateway.errors import (
    ProviderNotConfiguredError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from nevo.domain.ai_gateway.vocabulary import AiProviderName


class _ClaudeTextBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None


class _ClaudeUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class _ClaudeResponse(BaseModel):
    content: list[_ClaudeTextBlock] = Field(default_factory=list)
    model: str | None = None
    stop_reason: str | None = None
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
                },
                *request.history,
            ],
        }
        if request.tools:
            payload["tools"] = list(request.tools)
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
        tool_calls = tuple(
            ToolCall(id=block.id or "", name=block.name or "", arguments=block.input or {})
            for block in parsed.content
            if block.type == "tool_use" and block.id and block.name
        )
        # A turn that only asks for tools legitimately carries no text, so an
        # empty answer is only a failure when nothing was requested either.
        if not text and not tool_calls:
            raise ProviderResponseError
        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            raw_content=tuple(
                block.model_dump(exclude_none=True) for block in parsed.content
            ),
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
