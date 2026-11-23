"""Shadow mode: v2 is asked the same question and its answer changes nothing.

The point of these is the negative: whatever v2 says, and whatever goes wrong
while it says it, the request behaves exactly as it did before.
"""

import asyncio

import pytest

from nevo.ai_gateway.safety import ContentSafetyGuard, LessonSafetyContext

CTX = LessonSafetyContext(
    subject="Basic Science",
    level="Year 7",
    curriculum="NERDC Nigeria",
    source_type="teacher_upload",
    uploader_provenance="verified_school_staff",
    review_status="unreviewed",
)


def guard(**kw):
    return ContentSafetyGuard(api_key="test-key", **kw)


def test_shadow_is_off_unless_asked_for() -> None:
    assert guard()._shadow_v2 is False


def test_shadow_is_meaningless_when_v2_is_already_live() -> None:
    """Once v2 decides, there is nothing to shadow - and a guard that both
    enforced and shadowed v2 would ask the same question twice and bill for
    both."""
    assert guard(policy_v2=True, shadow_v2=True)._shadow_v2 is False


def test_the_sibling_never_shadows_again() -> None:
    """Otherwise each check spawns a check, which spawns a check."""
    parent = guard(shadow_v2=True)
    assert parent._shadow_v2 is True
    sibling = ContentSafetyGuard(
        api_key="test-key", policy_v2=True, shadow_v2=parent._shadow_v2
    )
    assert sibling._shadow_v2 is False


def test_a_shadow_that_blocks_does_not_block_the_request() -> None:
    """A v2 block is the single most interesting outcome and must still be
    swallowed: shadow mode exists to find disagreements, not to act on them."""
    from nevo.ai_gateway.safety import SafetyBlocked

    g = guard(shadow_v2=True)

    async def explode(*a, **k):
        raise SafetyBlocked(("self_harm",), "lesson_source")

    async def scenario():
        g._shadow_compare = explode
        g._fire_shadow("some lesson text", "lesson_source", None, CTX)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(scenario())  # no exception escapes


def test_a_shadow_that_errors_does_not_fail_the_request() -> None:
    g = guard(shadow_v2=True)

    async def explode(*a, **k):
        raise RuntimeError("checker fell over")

    async def scenario():
        g._shadow_compare = explode
        g._fire_shadow("some lesson text", "lesson_source", None, CTX)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_firing_without_a_loop_is_not_an_error() -> None:
    """Called from sync context it should shrug, not raise."""
    guard(shadow_v2=True)._fire_shadow("text", "lesson_source", None, CTX)


@pytest.mark.parametrize("flag", [True, False])
def test_the_factory_carries_the_flag_through(flag: bool) -> None:
    from nevo.ai_gateway.safety import safety_from_settings

    class Settings:
        anthropic_api_key = None
        anthropic_base_url = "https://api.anthropic.com/v1"
        anthropic_version = "2023-06-01"
        anthropic_model = "claude-haiku-4-5"
        safety_policy_v2_enabled = False
        safety_policy_v2_shadow = flag

    assert safety_from_settings(Settings())._shadow_v2 is flag
