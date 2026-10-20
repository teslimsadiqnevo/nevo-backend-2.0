import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nevo.ai_gateway.safety import ContentSafetyGuard, SafetyBlocked, SafetyUnavailable


def guard(decision, *, status=200, stop_reason="end_turn"):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            status,
            json={
                "stop_reason": stop_reason,
                "content": [{"type": "text", "text": decision}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return ContentSafetyGuard(api_key="test-only", client=client), calls, client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,exception",
    [
        ('{"action":"block","categories":["dangerous_instructions"]}', SafetyBlocked),
        ('{"action":"safeguard","categories":["self_harm"]}', SafetyBlocked),
        ('{"action":"allow","categories":["violence"]}', SafetyUnavailable),
        ('{"action":"block","categories":[]}', SafetyUnavailable),
        ('{"action":"allow","categories":[],"reason":"private text"}', SafetyUnavailable),
        ('{"action":"allow","categories":["unknown"]}', SafetyUnavailable),
        ("not JSON", SafetyUnavailable),
    ],
)
async def test_rejects_unsafe_or_invalid_review(decision, exception):
    reviewer, _, client = guard(decision)
    async with client:
        with pytest.raises(exception):
            await reviewer.check("untrusted material", phase="test")


@pytest.mark.asyncio
async def test_complete_long_input_is_reviewed_with_overlap():
    reviewer, calls, client = guard('{"action":"allow","categories":[]}')
    material = "a" * 16000 + "end-marker"
    async with client:
        await reviewer.check(material, phase="source")
    pieces = [json.loads(call["messages"][0]["content"][0]["text"])["material"] for call in calls]
    assert len(pieces) == 2
    assert pieces[0] + pieces[1][256:] == material
    assert "end-marker" in pieces[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,stop", [(429, "end_turn"), (200, "max_tokens")])
async def test_provider_failure_is_fail_closed(status, stop):
    reviewer, _, client = guard(
        '{"action":"allow","categories":[]}', status=status, stop_reason=stop
    )
    async with client:
        with pytest.raises(SafetyUnavailable):
            await reviewer.check("material", phase="source")


@pytest.mark.asyncio
async def test_missing_configuration_is_not_an_allow():
    with pytest.raises(SafetyUnavailable):
        await ContentSafetyGuard().check("hello", phase="source")


@pytest.mark.asyncio
async def test_forced_verdict_tool_is_validated():
    def respond(request):
        assert json.loads(request.content)["tool_choice"]["name"] == "content_safety_decision"
        return httpx.Response(
            200,
            json={
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "content_safety_decision",
                        "input": {"action": "allow", "categories": []},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await ContentSafetyGuard(api_key="test-only", client=client).check("lesson", phase="source")


@pytest.mark.asyncio
async def test_unsafe_input_never_calls_generation_provider():
    from tests.ai_gateway.fakes import SequenceProvider
    from tests.ai_gateway.test_service import request, service_with

    provider = SequenceProvider([])
    service, _, _ = service_with(provider)
    service._safety.check = AsyncMock(side_effect=SafetyBlocked())
    with pytest.raises(SafetyBlocked):
        await service.generate(request())
    assert provider.requests == []


@pytest.mark.asyncio
async def test_unsafe_output_is_not_returned():
    from tests.ai_gateway.fakes import SequenceProvider
    from tests.ai_gateway.test_service import provider_response, request, service_with

    service, _, _ = service_with(SequenceProvider([provider_response("unsafe output")]))
    service._safety.check = AsyncMock(side_effect=[None, SafetyBlocked()])
    with pytest.raises(SafetyBlocked):
        await service.generate(request())
