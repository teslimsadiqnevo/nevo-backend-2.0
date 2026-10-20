"""The two rewrites behind the adaptation engine's simplify and expand.

The engine has returned those two actions since it was built and nothing
stood behind either. These are the checks on what now does: that a rewrite
is refused when it cannot be trusted, and that refusing never costs the
lesson the text the teacher uploaded.
"""

import json
from uuid import uuid4

import pytest

from nevo.ai_gateway.entities import AiGenerationResult
from nevo.content_parsing.depth import (
    DepthVariantError,
    DepthVariants,
    DepthVariantService,
    accept,
    invented_numbers,
)
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.ai_gateway.vocabulary import AiProviderName, AiService
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType

from .test_service import FakeRepository

ACTOR = uuid4()

BODY = (
    "Simple interest is worked out from three things: the principal, which is "
    "the money you start with, the rate, which is the percentage charged each "
    "year, and the time in years. Multiply the three together and divide by "
    "100. If Ada saves 5000 naira at a rate of 4 per cent for 3 years, the "
    "interest is 600 naira, so she ends the period with 5600 naira in total."
)
SHORTER = (
    "Simple interest uses principal (money you start with), rate (percentage charged "
    "each year), and time in years. Multiply principal, rate and time; divide by 100. "
    "Ada saves 5000 naira at 4 per cent for 3 years: interest is 600 naira; "
    "the period ends with 5600 naira in total."
)


class Gateway:
    configured = True

    def __init__(self, text: str, *, fallback: bool = False) -> None:
        self.text = text
        self.fallback = fallback
        self.requests: list[object] = []

    async def generate(self, request):
        self.requests.append(request)
        return AiGenerationResult(
            text=self.text,
            provider=AiProviderName.CLAUDE,
            model="claude-haiku-4-5",
            prompt_name=request.prompt_name,
            prompt_version=1,
            fallback_used=self.fallback,
            compliance_retries=0,
            call_id=uuid4(),
        )


def service(text: str, *, fallback: bool = False) -> tuple[DepthVariantService, Gateway]:
    gateway = Gateway(text, fallback=fallback)
    return DepthVariantService(ai_gateway=gateway), gateway  # type: ignore[arg-type]


def segment(body: str = BODY) -> ParsedLessonSegment:
    return ParsedLessonSegment(
        segment_key="a",
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=1,
        title="Simple interest",
        body=body,
        available_modalities=(ContentModality.TEXT,),
    )


def test_a_figure_the_teacher_never_wrote_is_an_invented_one() -> None:
    assert invented_numbers("She saves 5000 for 3 years", BODY) == set()
    assert invented_numbers("She saves 7000 naira", BODY) == {"7000"}
    # A thousands separator is a way of writing a number, not a new number.
    assert invented_numbers("She saves 5,000 naira", BODY) == set()


def test_a_rewrite_that_invents_a_figure_is_dropped() -> None:
    # The failure the whole check exists for: a child reading the simpler
    # version of a worked example must not be reading a different sum.
    assert accept("Ada saves 9000 naira.", source=BODY, shorter=True) is None


def test_a_simpler_version_has_to_be_shorter_and_a_longer_one_longer() -> None:
    assert accept(BODY + " More words here.", source=BODY, shorter=True) is None
    assert accept("Short.", source=BODY, shorter=False) is None
    assert accept("Interest is 600 naira.", source=BODY, shorter=True) is None
    assert accept(SHORTER, source=BODY, shorter=True) is not None


def test_a_rewrite_identical_to_the_body_is_not_a_rewrite() -> None:
    assert accept(BODY, source=BODY, shorter=True) is None
    assert accept("   ", source=BODY, shorter=True) is None


def test_a_faithful_simplification_is_not_dropped_for_missing_ten_percent_by_a_few_chars():
    source = "A partially permeable membrane lets water pass through, but blocks larger particles."
    rewrite = "A partially permeable membrane lets water through, but blocks larger particles."
    assert 0.9 < len(rewrite) / len(source) < 1
    assert accept(rewrite, source=source, shorter=True) == rewrite


async def test_partial_depth_failure_has_a_segment_and_variant_review_note():
    longer = BODY + " " + BODY
    parsing = ContentParsingService(
        repository=FakeRepository(),
        ai_gateway=Gateway(json.dumps({"simplified": "Invented 9000 naira.", "expanded": longer})),
    )
    notes = []
    [result] = await parsing._generate_media([segment()], notes, requested_by_user_id=ACTOR)
    assert result.depth_variants["expanded"]["body"] == longer
    assert "simplified" not in result.depth_variants
    assert notes[0]["segment"] == "a" and notes[0]["variant"] == "simplified"
    assert notes[0]["code"] == "depth_variants_rejected"


async def test_rejected_simplification_is_retried_without_replacing_valid_expansion():
    longer = BODY + " " + BODY

    class CorrectingGateway(Gateway):
        async def generate(self, request):
            self.text = json.dumps(
                {
                    "simplified": BODY if not self.requests else SHORTER,
                    "expanded": longer if not self.requests else "Invalid later expansion.",
                }
            )
            return await super().generate(request)

    gateway = CorrectingGateway("")
    variants, _ = await DepthVariantService(ai_gateway=gateway).generate(
        title=None, body=BODY, requested_by_user_id=ACTOR
    )
    assert variants.simplified == SHORTER and variants.expanded == longer
    assert len(gateway.requests) == 2
    assert "not_shorter" not in variants.rejection_reasons.values()


async def test_both_versions_are_written_and_keyed_by_the_engines_actions() -> None:
    shorter = SHORTER
    longer = BODY + " " + BODY + " Work through each of the 3 years in turn."
    depth, gateway = service(f'{{"simplified": "{shorter}", "expanded": "{longer}"}}')

    variants, model = await depth.generate(
        title="Simple interest", body=BODY, requested_by_user_id=ACTOR
    )

    assert variants.simplified == shorter
    assert variants.expanded == longer
    assert model == "claude-haiku-4-5"
    # Parse-time work queues with the parse, not in the lane kept for calls
    # made while a child is waiting.
    assert gateway.requests[0].service is AiService.LESSON_GENERATION
    payload = variants.payload(model=model)
    assert payload["simplified"]["body"] == shorter
    assert payload["expanded"]["body"] == longer
    assert payload["simplified"]["reviewStatus"] == "pending"
    assert payload["expanded"]["reviewStatus"] == "pending"


async def test_a_fenced_answer_is_still_read() -> None:
    shorter = SHORTER
    depth, _ = service(f'```json\n{{"simplified": "{shorter}"}}\n```')

    variants, _ = await depth.generate(title=None, body=BODY, requested_by_user_id=ACTOR)

    assert variants.simplified == shorter
    assert variants.expanded is None


async def test_the_deterministic_fallback_is_refused() -> None:
    # It rewrites nothing, so keeping it would store the same text twice and
    # tell a child one of them was simpler.
    depth, _ = service('{"simplified": "Short one."}', fallback=True)

    with pytest.raises(DepthVariantError):
        await depth.generate(title=None, body=BODY, requested_by_user_id=ACTOR)


async def test_an_unreadable_answer_is_refused_rather_than_stored() -> None:
    depth, _ = service("I have rewritten the segment for you!")

    with pytest.raises(DepthVariantError):
        await depth.generate(title=None, body=BODY, requested_by_user_id=ACTOR)


async def test_invalid_json_gets_one_larger_strict_json_retry() -> None:
    class RecoveringGateway(Gateway):
        async def generate(self, request):
            self.text = "{" if not self.requests else f'{{"simplified":"{SHORTER}"}}'
            return await super().generate(request)

    gateway = RecoveringGateway("")
    variants, _ = await DepthVariantService(ai_gateway=gateway).generate(
        title=None, body=BODY, requested_by_user_id=ACTOR
    )
    assert variants.simplified == SHORTER
    assert len(gateway.requests) == 2
    assert gateway.requests[1].max_output_tokens > gateway.requests[0].max_output_tokens
    assert gateway.requests[0].json_output is True


def test_a_short_segment_is_not_worth_rewriting() -> None:
    depth, _ = service("{}")

    assert not depth.worth_rewriting("Interest is a charge for borrowing money.")
    assert depth.worth_rewriting(BODY)


async def test_a_failed_rewrite_costs_a_note_and_never_the_segment() -> None:
    parsing = ContentParsingService(
        repository=FakeRepository(),  # type: ignore[arg-type]
        ai_gateway=Gateway("not json"),  # type: ignore[arg-type]
    )
    notes: list[dict[str, object]] = []

    [result] = await parsing._generate_media([segment()], notes, requested_by_user_id=ACTOR)

    assert result.depth_variants is None
    assert result.body == BODY
    # Not a review flag: the teacher's own text is still what a child reads,
    # and an unwritten rewrite is not a fault in the lesson.
    assert not result.needs_review
    assert [note["code"] for note in notes] == ["depth_variants_failed"]


async def test_a_rewrite_that_fails_its_checks_is_reported_as_rejected() -> None:
    parsing = ContentParsingService(
        repository=FakeRepository(),  # type: ignore[arg-type]
        ai_gateway=Gateway('{"simplified": "Ada saves 9000 naira.", "expanded": "Tiny."}'),  # type: ignore[arg-type]
    )
    notes: list[dict[str, object]] = []

    [result] = await parsing._generate_media([segment()], notes, requested_by_user_id=ACTOR)

    assert result.depth_variants is None
    assert [note["code"] for note in notes] == ["depth_variants_rejected"]


def test_variants_with_nothing_in_them_are_empty() -> None:
    assert DepthVariants(simplified=None, expanded=None).empty
    assert not DepthVariants(simplified="x", expanded=None).empty


def test_normalize_segment_preserves_depth_variants() -> None:
    from nevo.content_parsing.service import _normalize_segment

    sample = segment()
    with_depth = ParsedLessonSegment(
        segment_key=sample.segment_key,
        content_type=sample.content_type,
        sequence_order=sample.sequence_order,
        title=sample.title,
        body=sample.body,
        available_modalities=sample.available_modalities,
        depth_variants={"simplified": {"body": "Shorter."}, "expanded": {"body": "Longer."}},
    )
    normalized = _normalize_segment(with_depth)
    assert normalized.depth_variants == {
        "simplified": {"body": "Shorter."},
        "expanded": {"body": "Longer."},
    }
