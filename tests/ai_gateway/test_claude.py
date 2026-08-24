import json

import httpx

from nevo.ai_gateway.claude import ClaudeRestProvider
from nevo.ai_gateway.entities import ProviderRequest
from nevo.domain.ai_gateway.vocabulary import AiProviderName


async def test_claude_provider_uses_messages_api_and_prompt_caching() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.url.params.get("key") is None
        payload = json.loads(request.read().decode())
        assert payload["model"] == "claude-haiku-4-5"
        assert payload["max_tokens"] == 256
        assert payload["cache_control"] == {"type": "ephemeral"}
        assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert payload["messages"][0]["content"][0]["text"] == "Teacher source"
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Grounded response."}],
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 900,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ClaudeRestProvider(
        api_key="secret",
        model="claude-haiku-4-5",
        base_url="https://api.anthropic.com/v1",
        anthropic_version="2023-06-01",
        timeout_seconds=5,
        prompt_caching_enabled=True,
        client=client,
    )

    result = await provider.generate(
        ProviderRequest(
            system_instruction="Use the source.",
            user_content="Teacher source",
            max_output_tokens=256,
        )
    )

    assert result.text == "Grounded response."
    assert result.provider is AiProviderName.CLAUDE
    assert result.model == "claude-haiku-4-5"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.cache_creation_input_tokens == 100
    assert result.cache_read_input_tokens == 900
    await client.aclose()


async def test_claude_provider_allows_sonnet_step_up_per_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode())
        assert payload["model"] == "claude-sonnet"
        assert "cache_control" not in payload
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Structured lesson."}],
                "model": "claude-sonnet",
                "usage": {"input_tokens": 50, "output_tokens": 20},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ClaudeRestProvider(
        api_key="secret",
        model="claude-haiku-4-5",
        base_url="https://api.anthropic.com/v1",
        anthropic_version="2023-06-01",
        timeout_seconds=5,
        prompt_caching_enabled=True,
        client=client,
    )

    result = await provider.generate(
        ProviderRequest(
            system_instruction="Use the source.",
            user_content="Teacher source",
            max_output_tokens=256,
            model="claude-sonnet",
            cache_prompt=False,
        )
    )

    assert result.model == "claude-sonnet"
    await client.aclose()
