import httpx

from nevo.ai_gateway.entities import ProviderRequest
from nevo.ai_gateway.gemini import GeminiRestProvider
from nevo.domain.ai_gateway.vocabulary import AiProviderName


async def test_gemini_provider_uses_header_auth_and_parses_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "secret"
        assert request.url.params.get("key") is None
        payload = request.read().decode()
        assert "Teacher source" in payload
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Grounded response."}]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 11,
                    "candidatesTokenCount": 7,
                    "thoughtsTokenCount": 3,
                },
                "modelVersion": "gemini-test-001",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GeminiRestProvider(
        api_key="secret",
        model="gemini-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds=5,
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
    assert result.provider is AiProviderName.GEMINI
    assert result.model == "gemini-test-001"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.thought_tokens == 3
    await client.aclose()
