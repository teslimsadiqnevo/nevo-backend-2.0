import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nevo.ai_gateway.safety import (
    ContentSafetyGuard,
    LessonSafetyContext,
    SafetyBlocked,
    SafetyUnavailable,
)


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finding,expected",
    [
        (
            {
                "category": "dangerous_instructions",
                "finding_type": "hazardous_action",
                "confidence": "high",
            },
            "block",
        ),
        (
            {
                "category": "privacy_abuse",
                "finding_type": "exposed_credentials",
                "confidence": "high",
            },
            "block",
        ),
        (
            {"category": "violence", "finding_type": "historical_account", "confidence": "high"},
            "record",
        ),
        (
            {"category": "privacy_abuse", "finding_type": "ordinary_name", "confidence": "high"},
            "record",
        ),
        (
            {
                "category": "privacy_abuse",
                "finding_type": "ordinary_name",
                "confidence": "uncertain",
            },
            "hold",
        ),
        ({"category": "privacy_abuse", "finding_type": "other", "confidence": "high"}, "block"),
    ],
)
async def test_v2_lesson_policy_uses_typed_context_and_finding_type(finding, expected):
    payloads = []

    def respond(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        return httpx.Response(
            200,
            json={
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "content_safety_decision",
                        "input": {"findings": [finding]},
                    }
                ],
            },
        )

    context = LessonSafetyContext(
        subject="History",
        level="SS1",
        curriculum="Nigerian curriculum",
        source_type="pdf",
        uploader_provenance="authenticated_account",
        review_status="not_reviewed",
        section_id="section-1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reviewer = ContentSafetyGuard(api_key="test-only", client=client, policy_v2=True)
        if expected == "record":
            await reviewer.check("lesson material", phase="lesson_source", lesson_context=context)
        else:
            with pytest.raises(SafetyBlocked) as caught:
                await reviewer.check(
                    "lesson material", phase="lesson_source", lesson_context=context
                )
            assert caught.value.disposition == expected
    submitted = json.loads(payloads[0]["messages"][0]["content"][0]["text"])
    assert submitted["lessonContext"]["section_id"] == "section-1"
    assert submitted["lessonContext"]["subject"] == "History"
    assert submitted["phase"] == "lesson_source"


@pytest.mark.asyncio
async def test_v2_requires_context_and_checker_failure_does_not_become_a_finding():
    reviewer, calls, client = guard('{"findings": []}')
    reviewer._policy_v2 = True
    async with client:
        with pytest.raises(SafetyUnavailable):
            await reviewer.check("lesson material", phase="lesson_source")
    assert calls == []


def test_an_image_safety_check_gets_room_to_upload_the_image() -> None:
    """30s flat was a quarter of what the reviewer gets for the same bytes.

    The image phases send a megabyte and a half of PNG as base64. httpx's
    flat timeout applies to the write as well as the read, so pushing that
    in 30s needed a fast uplink; without one it raised WriteTimeout, which
    is caught with the other HTTP errors and reaches a teacher as "Nevo
    cannot complete its safety check right now" - a message that names no
    cause and suggests the checker, not the clock. The image reviewer sends
    identical bytes with 120s and succeeds.
    """
    from nevo.ai_gateway.safety import _timeout_for

    text_only = _timeout_for(None)
    assert text_only.write == 30.0 and text_only.read == 30.0, "text is unchanged"

    with_image = _timeout_for(b"\x89PNG" + b"0" * 1_500_000)
    assert with_image.write == 120.0, "the write is what was timing out"
    assert with_image.read == 120.0
    assert with_image.connect == 30.0, "a dead host should still fail fast"
