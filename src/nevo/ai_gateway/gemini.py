from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nevo.ai_gateway.entities import ProviderRequest, ProviderResponse
from nevo.ai_gateway.errors import (
    ProviderResponseError,
    ProviderUnavailableError,
)
from nevo.domain.ai_gateway.vocabulary import AiProviderName


class _GeminiPart(BaseModel):
    text: str | None = None


class _GeminiContent(BaseModel):
    parts: list[_GeminiPart] = Field(default_factory=list)


class _GeminiCandidate(BaseModel):
    content: _GeminiContent | None = None


class _GeminiUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prompt_token_count: int = Field(default=0, alias="promptTokenCount")
    candidates_token_count: int = Field(
        default=0,
        alias="candidatesTokenCount",
    )
    thoughts_token_count: int = Field(default=0, alias="thoughtsTokenCount")


class _GeminiResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    candidates: list[_GeminiCandidate] = Field(default_factory=list)
    usage_metadata: _GeminiUsage = Field(
        default_factory=_GeminiUsage,
        alias="usageMetadata",
    )
    model_version: str | None = Field(default=None, alias="modelVersion")


class GeminiRestProvider:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )
        self._owns_client = client is None

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self._api_key:
            raise ProviderUnavailableError
        endpoint = (
            f"{self._base_url}/models/"
            f"{quote(self._model, safe='-._')}:generateContent"
        )
        payload: dict[str, Any] = {
            "systemInstruction": {
                "parts": [{"text": request.system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.user_content}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        try:
            response = await self._client.post(
                endpoint,
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            parsed = _GeminiResponse.model_validate(response.json())
        except (
            httpx.HTTPError,
            ValueError,
            ValidationError,
        ) as error:
            raise ProviderUnavailableError from error

        text = "".join(
            part.text or ""
            for candidate in parsed.candidates
            if candidate.content is not None
            for part in candidate.content.parts
        ).strip()
        if not text:
            raise ProviderResponseError
        usage = parsed.usage_metadata
        return ProviderResponse(
            text=text,
            provider=AiProviderName.GEMINI,
            model=parsed.model_version or self._model,
            input_tokens=usage.prompt_token_count,
            output_tokens=usage.candidates_token_count,
            thought_tokens=usage.thoughts_token_count,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
