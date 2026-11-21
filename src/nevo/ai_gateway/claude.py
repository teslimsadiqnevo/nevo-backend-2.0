import base64
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
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
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
                        # Images first, then the text that asks about them.
                        # The provider reads the content in order, and an
                        # instruction that arrives before the picture it
                        # refers to is an instruction about nothing.
                        *(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image.media_type,
                                    "data": base64.b64encode(image.data).decode(),
                                },
                            }
                            for image in request.images
                        ),
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
            # Caching is a prefix match over tools -> system -> messages, and
            # a breakpoint caches everything up to and including the block it
            # sits on. Two breakpoints, deliberately:
            #
            # The system instruction, as before. It is identical across every
            # chunk of one lesson, so this is the half that was already
            # paying off.
            #
            # And the user content, which is the uploaded document. That was
            # never cached, so a retry of the same chunk re-sent and re-paid
            # for the whole thing. A cache read costs a tenth of a fresh read
            # and lesson preparation is almost all of our model spend, so
            # this is the cheapest saving available to us. L6, 20 November.
            payload["system"][0]["cache_control"] = {"type": "ephemeral"}
            # The last block, which is always the text: images are placed
            # before it. A breakpoint on an image would cache a photograph of
            # a child's exercise book on the provider's side for the cache
            # lifetime, which ADR 0009 does not permit - it says the image is
            # held for the read and then gone.
            if not request.images:
                payload["messages"][0]["content"][-1]["cache_control"] = {
                    "type": "ephemeral"
                }
            # The top-level "cache_control" that used to be set here did
            # nothing at all: the Messages API takes cache_control on content
            # blocks, not on the request. It read like caching was on while
            # only the system block was actually cached.

        try:
            response = await self._client.post(
                f"{self._base_url}/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": self._anthropic_version,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=(
                    httpx.Timeout(request.timeout_seconds)
                    if request.timeout_seconds is not None
                    else httpx.USE_CLIENT_DEFAULT
                ),
            )
            response.raise_for_status()
            parsed = _ClaudeResponse.model_validate(response.json())
        except (
            httpx.HTTPError,
            ValueError,
            ValidationError,
        ) as error:
            raise ProviderUnavailableError from error

        text = "".join(block.text or "" for block in parsed.content if block.type == "text").strip()
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
            raw_content=tuple(block.model_dump(exclude_none=True) for block in parsed.content),
            provider=AiProviderName.CLAUDE,
            model=parsed.model or request.model or self._model,
            stop_reason=parsed.stop_reason,
            input_tokens=parsed.usage.input_tokens,
            output_tokens=parsed.usage.output_tokens,
            cache_creation_input_tokens=parsed.usage.cache_creation_input_tokens,
            cache_read_input_tokens=parsed.usage.cache_read_input_tokens,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
