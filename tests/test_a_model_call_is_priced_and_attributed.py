"""A model call records what it was for and what it really cost.

Lydia, 20 November: everything about pricing is blocked on the per-learner
runtime cost of one lesson. Three things stood in the way, and all three were
bookkeeping rather than instrumentation.

One flat price pair was applied to every model, and it was the cheapest
model's - $1 in, $5 out, which is Haiku 4.5 exactly. Of 2,626 recorded calls
872 ran on Sonnet 5 and 11 on Sonnet 4.6, all billed at Haiku's rate, so the
all-time figure read $9.97 when it was about $15.70.

The call did not know its lesson, so "one learner across one lesson" could
only be asked of a time window - and the lesson id was already arriving on
the safety context, unrecorded.

And the cache counts the cost formula depends on were stored nowhere, so
"is prompt caching working" had no answer at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from nevo.ai_gateway.config import AiGatewaySettings
from nevo.ai_gateway.safety import LessonSafetyContext
from nevo.ai_gateway.service import AiGatewayService, _lesson_uuid
from nevo.db.models.ai_gateway import AiGatewayCall

LESSON = "3367de9d-be40-4704-8a95-7a197b9824dc"


def _gateway(*, configured: bool) -> AiGatewayService:
    service = AiGatewayService.__new__(AiGatewayService)
    service._input_cost = Decimal("1")
    service._output_cost = Decimal("5")
    service._cache_write_cost = Decimal("1.25")
    service._cache_read_cost = Decimal("0.10")
    service._prices_are_configured = configured
    return service


def _cost(service: AiGatewayService, model: str | None, **tokens: int) -> Decimal:
    return service._estimated_cost(
        input_tokens=tokens.get("input", 0),
        output_tokens=tokens.get("output", 0),
        thought_tokens=0,
        cache_creation_input_tokens=tokens.get("cache_write", 0),
        cache_read_input_tokens=tokens.get("cache_read", 0),
        model=model,
    )


def test_sonnet_is_not_billed_at_haikus_rate() -> None:
    """The specific error that understated the all-time figure by a third."""
    service = _gateway(configured=False)
    haiku = _cost(service, "claude-haiku-4-5", input=1_000_000)
    sonnet = _cost(service, "claude-sonnet-5", input=1_000_000)
    assert sonnet == haiku * 2


def test_a_dated_snapshot_prices_as_its_family() -> None:
    """Every real recorded call names a snapshot, not a bare family."""
    service = _gateway(configured=False)
    assert _cost(service, "claude-haiku-4-5-20251001", input=1_000_000) == _cost(
        service, "claude-haiku-4-5", input=1_000_000
    )


def test_an_unpriced_model_falls_back_rather_than_reading_zero() -> None:
    """A model nobody has priced must not record as free."""
    service = _gateway(configured=False)
    assert _cost(service, "some-new-model", input=1_000_000) == Decimal("1")
    assert _cost(service, None, input=1_000_000) == Decimal("1")


def test_a_stated_price_is_never_replaced_by_a_list_price() -> None:
    """A negotiated rate must win. The table is a fallback, not an override.

    This is the trap the change first walked into: the table silently
    replaced prices a caller had deliberately passed in.
    """
    configured = _gateway(configured=True)
    assert _cost(configured, "claude-sonnet-5", input=1_000_000) == Decimal("1")
    assert _cost(configured, "claude-opus-5", output=1_000_000) == Decimal("5")


def test_a_cache_read_is_a_tenth_of_a_fresh_read() -> None:
    """The reason caching is worth anything at all."""
    service = _gateway(configured=False)
    fresh = _cost(service, "claude-sonnet-5", input=1_000_000)
    cached = _cost(service, "claude-sonnet-5", cache_read=1_000_000)
    assert cached * 10 == fresh


@pytest.mark.parametrize(
    "model", ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5-5"]
)
def test_every_priced_model_has_all_four_rates(model: str) -> None:
    rates = AiGatewaySettings.MODEL_PRICES[model]
    assert len(rates) == 4
    assert all(Decimal(rate) > 0 for rate in rates)


def test_the_call_row_can_carry_its_lesson_and_cache_counts() -> None:
    columns = AiGatewayCall.__table__.c
    assert columns.lesson_id.nullable, "a call may belong to no lesson"
    assert columns.cache_creation_input_tokens.nullable is False
    assert columns.cache_read_input_tokens.nullable is False


def test_the_lesson_comes_off_the_context_already_being_passed() -> None:
    context = LessonSafetyContext(
        subject="s",
        level="l",
        curriculum="c",
        source_type="pdf",
        uploader_provenance="u",
        review_status="r",
        lesson_id=LESSON,
    )
    assert str(_lesson_uuid(context)) == LESSON


def test_an_unusable_lesson_id_costs_nothing() -> None:
    """The provider has already billed the call; losing the audit row over a
    malformed id would be the worse failure."""
    assert _lesson_uuid(None) is None
    bad = LessonSafetyContext(
        subject="s",
        level="l",
        curriculum="c",
        source_type="pdf",
        uploader_provenance="u",
        review_status="r",
        lesson_id="not-a-uuid",
    )
    assert _lesson_uuid(bad) is None
