import asyncio
import json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.errors import AiGatewayError
from nevo.ai_gateway.service import AiGatewayService
from nevo.api.lesson_contracts import checkpoint_payloads
from nevo.audio.service import AudioGenerationError, AudioGenerationService
from nevo.content_parsing.entities import (
    ContentParseRequest,
    ParsedLesson,
    ParsedLessonSegment,
    ParseRunState,
    SourcePage,
    StoredParsedLesson,
)
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    LessonContentType,
    LessonSourceType,
    ManipulativeKind,
    SegmentReviewReason,
)
from nevo.visuals import EducationalImageService, VisualGenerationError

logger = logging.getLogger(__name__)

STALE_RUN_AFTER = timedelta(minutes=30)
"""Longer than any real parse, short enough that nobody polls a dead run for
an afternoon."""

PARSE_OUTPUT_TOKENS = 16_384
"""Room for the lesson the prompt actually asks for.

The prompt requires at least three segments, each with variants, checkpoints
and a narration script. At 4,096 tokens the model ran out of room mid-object
and every response failed to parse, so every lesson in the library was
deterministic fallback while the call log said the provider had succeeded.
"""

GENERATION_CONCURRENCY = 2
"""How many segments have their media made at once.

Sequential cost a lesson the sum of every generation. Unbounded went the
other way and lost media to provider rate limits - a four-segment lesson
came back missing audio on two segments and a picture on a third. Two at a
time keeps most of the speed without hammering the provider.
"""

PARSE_TIMEOUT_SECONDS = 180.0
"""A lesson takes minutes to write, not the twenty seconds a question takes.

Raising the token budget without this simply moved the failure: the model
was still writing when the shared twenty-second ceiling cut it off, and the
gateway recorded provider_unavailable and fell back to splitting the source.
"""

#: How much the parse writes per character of source, measured on a real run:
#: 4,612 characters of Simple Interest came back as 9,004 output tokens. Every
#: character of a lesson becomes roughly two tokens of structured answer, since
#: the source is rewritten into segments, variants, checkpoints and a narration
#: script rather than summarised.
OUTPUT_TOKENS_PER_SOURCE_CHAR = 2.0

#: Headroom, because the ratio is an average over four documents and a verbose
#: run on a dense one should still fit.
CHUNK_HEADROOM = 0.8

#: Derived, never set by hand. These two numbers were independent constants and
#: drifted into contradiction: a chunk was allowed to be 24,000 characters while
#: the answer to it was capped at 16,384 tokens, which is about a third of what
#: 24,000 characters needs. Any document long enough to fill a chunk could not
#: be answered inside the budget, so it was cut off mid-object and the whole
#: lesson fell back to the deterministic splitter.
MAX_CHUNK_CHARS = int(PARSE_OUTPUT_TOKENS / OUTPUT_TOKENS_PER_SOURCE_CHAR * CHUNK_HEADROOM)
PROMPT_NAME = "content_parse.default"
CALCULATION_INPUT_TYPES = {"selection", "numeric", "text", "drag"}
#: The kinds that need something on screen to choose between. Numeric and text
#: are typed, so an empty options list is correct for those and only those.
CHOICE_INPUT_TYPES = {"selection", "drag"}
AI_GENERATED_IMAGE_TYPE = "ai_generated_image"


class ContentParsingService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyContentParsingRepository,
        ai_gateway: AiGatewayService,
        audio_generation: AudioGenerationService | None = None,
        visual_generation: EducationalImageService | None = None,
    ) -> None:
        self._repository = repository
        self._ai_gateway = ai_gateway
        self._audio_generation = audio_generation
        self._visual_generation = visual_generation
        self._running: set[asyncio.Task[None]] = set()
        self._media_notes: list[dict[str, object]] = []

    async def start(
        self,
        *,
        request: ContentParseRequest,
        requested_by_user_id: UUID,
        existing_lesson_id: UUID | None = None,
    ) -> tuple[UUID, UUID]:
        """Record the run, hand back its id, and do the work behind it.

        A full parse is minutes of image generation and speech synthesis, so
        it cannot be an HTTP request that a client waits on: every proxy
        between here and the browser will hang up first, and hanging up on
        work that is still running is indistinguishable from a backend that
        never answers.

        Returns ``(lesson_id, parse_run_id)``. The run id is what the client
        polls.
        """
        lesson_id, parse_run_id = await self._repository.begin_run(
            request=request,
            requested_by_user_id=requested_by_user_id,
            existing_lesson_id=existing_lesson_id,
        )
        task = asyncio.create_task(
            self._run(
                request=request,
                requested_by_user_id=requested_by_user_id,
                lesson_id=lesson_id,
                parse_run_id=parse_run_id,
            ),
            name=f"content-parse-{parse_run_id}",
        )
        # Held so the task is not garbage collected mid-flight.
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        return lesson_id, parse_run_id

    async def _run(
        self,
        *,
        request: ContentParseRequest,
        requested_by_user_id: UUID,
        lesson_id: UUID,
        parse_run_id: UUID,
    ) -> None:
        try:
            await self.parse(
                request=request,
                requested_by_user_id=requested_by_user_id,
                existing_lesson_id=lesson_id,
                parse_run_id=parse_run_id,
            )
        except Exception as error:
            # Whatever went wrong, the run must stop saying "processing".
            logger.exception("Content parse run %s failed", parse_run_id)
            await self._repository.fail_run(
                parse_run_id,
                reason=f"{error.__class__.__name__}: {error}",
            )

    async def run_state(self, parse_run_id: UUID) -> ParseRunState | None:
        return await self._repository.run_state(parse_run_id)

    async def fail_stale_runs(self, *, older_than: timedelta = STALE_RUN_AFTER) -> int:
        return await self._repository.fail_stale_runs(older_than=older_than)

    async def parse(
        self,
        *,
        request: ContentParseRequest,
        requested_by_user_id: UUID,
        existing_lesson_id: UUID | None = None,
        parse_run_id: UUID | None = None,
    ) -> StoredParsedLesson:
        source = _source_for_prompt(request)
        chunks = _chunks(source)
        # Reset per parse: media notes belong to the lesson being built, not
        # to whatever this service happened to build before it.
        self._media_notes = []
        segments: list[ParsedLessonSegment] = []
        review_notes: list[dict[str, object]] = []
        ai_call_count = 0
        recap: str | None = None
        title: str | None = None
        assessment: list[dict[str, object]] = []

        for index, chunk in enumerate(chunks, start=1):
            try:
                result = await self._ai_gateway.generate(
                    AiGenerationRequest(
                        requester_user_id=requested_by_user_id,
                        service=AiService.LESSON_GENERATION,
                        prompt_name=PROMPT_NAME,
                        variables={
                            "lesson_title": request.title,
                            "source_type": request.source_type.value,
                            "chunk_number": str(index),
                            "chunk_count": str(len(chunks)),
                            "source_text": chunk,
                        },
                        max_output_tokens=PARSE_OUTPUT_TOKENS,
                        timeout_seconds=PARSE_TIMEOUT_SECONDS,
                    )
                )
                ai_call_count += 1
                payload = _json_payload(result.text)
                segments.extend(
                    _segments_from_payload_list(
                        payload,
                        sequence_offset=len(segments),
                    )
                )
                # The lesson's ending comes from whichever chunk wrote one.
                # A multi-chunk source closes once, not once per chunk.
                recap = recap or _optional_string(payload.get("recap"))
                # Likewise its name. The filename is a fallback, not a title:
                # nobody writing a lesson is naming it for a teacher's library.
                title = title or _lesson_title(payload.get("title"))
                if not assessment:
                    assessment = _assessment_questions(payload)
            except (AiGatewayError, ValueError, json.JSONDecodeError) as error:
                # Say what went wrong, not just that something did. This note
                # was the only record that the AI had contributed nothing, and
                # it named the exception class and no more - which is how a
                # whole library of fallback lessons went unnoticed.
                review_notes.append(
                    {
                        "code": "ai_parse_fallback",
                        "chunkNumber": index,
                        "message": (
                            "This chunk used deterministic parsing because the AI "
                            "could not return valid structured lesson data."
                        ),
                        "error": error.__class__.__name__,
                        "reason": str(error)[:300],
                        **_response_forensics(locals().get("result")),
                        "pageNumbers": [
                            int(value) for value in re.findall(r"\[Page (\d+)\]", chunk)
                        ],
                    }
                )
                segments.extend(
                    _fallback_segments(
                        chunk,
                        sequence_offset=len(segments),
                    )
                )

        # Segments are independent, so their media is made concurrently rather
        # than one lesson-length queue at a time - but only a couple at once,
        # because the providers rate limit and a dropped image is a segment
        # the learner never sees.
        prepared_segments = list(segments)
        if self._visual_generation is not None and self._visual_generation.configured:
            prepared_segments = await _in_parallel(
                self._generate_segment_visual,
                prepared_segments,
            )
        if self._audio_generation is not None and self._audio_generation.configured:
            prepared_segments = await _in_parallel(
                self._generate_segment_audio,
                prepared_segments,
            )
        normalized_segments = [_normalize_segment(segment) for segment in prepared_segments]

        review_notes.extend(self._media_notes)
        parsed = ParsedLesson(
            title=title or request.title,
            segments=tuple(normalized_segments),
            review_notes=tuple(review_notes),
            confirmation_summary=_confirmation_summary(segments),
            recap=recap,
            assessment=tuple(assessment),
            gemini_call_count=ai_call_count,
            chunk_count=len(chunks),
        )
        return await self._repository.store(
            request=request,
            parsed=parsed,
            requested_by_user_id=requested_by_user_id,
            existing_lesson_id=existing_lesson_id,
            parse_run_id=parse_run_id,
        )

    async def _generate_segment_audio(
        self,
        segment: ParsedLessonSegment,
    ) -> ParsedLessonSegment:
        generator = self._audio_generation
        if generator is None:
            return segment
        reasons = list(segment.review_reasons)
        needs_review = segment.needs_review
        audio_variant = segment.audio_variant
        calculation_variant = segment.calculation_variant

        if audio_variant is not None:
            try:
                audio_variant = await generator.generate(
                    str(audio_variant.get("script") or segment.body)
                )
            except AudioGenerationError as error:
                needs_review = True
                reasons.append("audio_generation_failed")
                self._media_notes.append(
                    {
                        "code": "audio_generation_failed",
                        "segment": segment.segment_key,
                        "reason": str(error)[:300],
                    }
                )

        if calculation_variant is not None:
            calculation_variant = dict(calculation_variant)
            generated_steps: list[dict[str, object]] = []
            for step in _dict_list(calculation_variant.get("steps")):
                generated_step = dict(step)
                narration = _dict_or_none(step.get("narrationAudio"))
                if narration is not None:
                    try:
                        generated_audio = await generator.generate(
                            str(narration.get("script") or step.get("prompt") or "")
                        )
                        generated_step["narrationAudio"] = {
                            **generated_audio,
                            "stepId": str(step.get("stepId") or ""),
                        }
                    except AudioGenerationError:
                        needs_review = True
                        reasons.append("calculation_audio_generation_failed")
                generated_steps.append(generated_step)
            calculation_variant["steps"] = generated_steps

        return replace(
            segment,
            audio_variant=audio_variant,
            calculation_variant=calculation_variant,
            needs_review=needs_review,
            review_reasons=tuple(dict.fromkeys(reasons)),
        )

    async def _generate_segment_visual(
        self,
        segment: ParsedLessonSegment,
    ) -> ParsedLessonSegment:
        generator = self._visual_generation
        if generator is None or ContentModality.VISUAL not in segment.available_modalities:
            return segment
        requested_prompt = None
        if segment.visual_variant is not None:
            requested_prompt = _optional_string(segment.visual_variant.get("prompt"))
        started = time.perf_counter()
        try:
            visual = await generator.generate(
                title=segment.title,
                lesson_text=segment.body,
                requested_prompt=requested_prompt,
            )
        except VisualGenerationError as error:
            # Into the run's notes, not only the log. "visual_generation_failed"
            # on its own told nobody why, which is how every image in a lesson
            # went missing for two days without anyone being able to say what
            # had gone wrong.
            self._media_notes.append(
                {
                    "code": "visual_generation_failed",
                    "segment": segment.segment_key,
                    "reason": str(error)[:300],
                    "secondsSpent": round(time.perf_counter() - started, 1),
                }
            )
            return replace(
                segment,
                visual_variant=None,
                needs_review=True,
                review_reasons=tuple(
                    dict.fromkeys((*segment.review_reasons, "visual_generation_failed"))
                ),
            )
        return replace(segment, visual_variant=visual)


def _source_for_prompt(request: ContentParseRequest) -> str:
    if request.pages:
        return "\n\n".join(_page_text(page) for page in request.pages)
    if request.source_text and request.source_text.strip():
        return request.source_text.strip()
    reference = request.source_metadata.get("importReference")
    if request.source_type in {
        LessonSourceType.GOOGLE_DRIVE,
        LessonSourceType.ONEDRIVE,
    } and isinstance(reference, str):
        return reference
    raise ValueError("content parsing requires source text, pages, or import reference")


def _page_text(page: SourcePage) -> str:
    return f"[Page {page.page_number}]\n{page.text.strip()}"


def _chunks(source: str) -> list[str]:
    source = source.strip()
    if len(source) <= MAX_CHUNK_CHARS:
        return [source]
    paragraphs = re.split(r"\n{2,}", source)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if len(candidate) > MAX_CHUNK_CHARS and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _assessment_questions(payload: dict[str, object]) -> list[dict[str, object]]:
    """The questions a lesson closes on, in checkpoint shape.

    Same shape as a segment checkpoint on purpose: one renderer serves both,
    and a client that can already ask a mid-lesson question can ask an
    end-of-lesson one without new code.
    """
    return checkpoint_payloads(
        _dict_list(payload.get("assessment")),
        segment_key="lesson-assessment",
    )


def _segments_from_payload_list(
    payload: dict[str, object],
    *,
    sequence_offset: int,
) -> list[ParsedLessonSegment]:
    items = _dict_list(payload.get("segments"))
    if not items:
        raise ValueError("AI provider payload had no segments")
    return [
        _segment_from_payload(item, sequence_order=sequence_offset + index)
        for index, item in enumerate(items, start=1)
    ]


def _segments_from_ai(
    text: str,
    *,
    sequence_offset: int,
) -> tuple[ParsedLessonSegment, ...]:
    payload = _json_payload(text)
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("AI provider returned no parseable segments")
    parsed: list[ParsedLessonSegment] = []
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        parsed.append(
            _segment_from_payload(
                item,
                sequence_order=sequence_offset + index,
            )
        )
    if not parsed:
        raise ValueError("AI provider returned only malformed segments")
    return tuple(parsed)


async def _in_parallel(
    step: Callable[[ParsedLessonSegment], Awaitable[ParsedLessonSegment]],
    segments: list[ParsedLessonSegment],
) -> list[ParsedLessonSegment]:
    limit = asyncio.Semaphore(GENERATION_CONCURRENCY)

    async def bounded(segment: ParsedLessonSegment) -> ParsedLessonSegment:
        async with limit:
            return await step(segment)

    return list(await asyncio.gather(*(bounded(segment) for segment in segments)))


def _duration_ms(value: object) -> int | None:
    """Keep a measured length, and keep not-measured as not-measured."""
    if not isinstance(value, (int, float, str)):
        return None
    try:
        measured = int(value)
    except (TypeError, ValueError):
        return None
    return measured or None


def _response_forensics(result: object) -> dict[str, object]:
    """Enough about the answer to tell a cut-off one from a badly written one.

    These need opposite fixes - more room versus a better prompt - and the
    exception alone cannot tell them apart. This used to be guessed by counting
    braces across the whole response, which was wrong twice over: the parser
    reads a slice from the first brace to the LAST one, so an answer cut off
    mid-object gets trimmed to something balanced, and the guess then described
    text the parser had never seen. It reported "not truncated" on a response
    that ended at character 24,537 of its own output.

    So stop guessing. The provider says why it stopped; "max_tokens" is the
    answer being cut off and nothing else is.
    """

    text = getattr(result, "text", None)
    text = text if isinstance(text, str) else ""
    stop_reason = getattr(result, "stop_reason", None)
    forensics: dict[str, object] = {
        "stopReason": stop_reason,
        "truncated": stop_reason == "max_tokens",
        "responseChars": len(text),
        "outputTokens": getattr(result, "output_tokens", 0),
    }
    if text:
        # The last of what the parser actually tried to read. A cut-off answer
        # ends mid-key or mid-number and says so at a glance.
        forensics["responseTail"] = text.strip()[-180:]
    return forensics


def _json_payload(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("missing JSON object", stripped, 0)
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI provider payload must be a JSON object")
    return payload


def _segment_from_payload(
    item: dict[str, object],
    *,
    sequence_order: int,
) -> ParsedLessonSegment:
    content_type = _content_type(str(item.get("content_type", "")))
    body = str(item.get("body") or item.get("text") or "").strip()
    if not body:
        body = str(item.get("title") or "Review this segment.").strip()
    raw_modalities = item.get("availableModalities") or item.get("available_modalities")
    modalities = _modalities(raw_modalities)
    calculation_variant = _dict_or_none(item.get("calculation_variant"))
    review_reasons = _review_reasons(item.get("review_reasons"))
    needs_review = bool(item.get("needs_review")) or bool(item.get("needsReview"))
    if calculation_variant is not None:
        content_type = LessonContentType.CALCULATION
        modalities = (ContentModality.INTERACTIVE, ContentModality.VISUAL)
        calculation_variant, calculation_review = _validated_calculation_variant(
            calculation_variant,
        )
        if calculation_review:
            review_reasons.append(calculation_review)
            needs_review = True
    checkpoints = _dict_list(
        item.get("comprehension_checkpoints") or item.get("comprehensionCheckpoints")
    )
    for checkpoint in checkpoints:
        checkpoint.setdefault(
            "conceptName",
            str(item.get("concept_name") or item.get("title") or body[:80]),
        )
    return ParsedLessonSegment(
        segment_key=str(item.get("segment_key") or f"segment-{sequence_order}"),
        content_type=content_type,
        sequence_order=sequence_order,
        title=_optional_string(item.get("title")),
        body=body,
        available_modalities=modalities,
        comprehension_checkpoints=tuple(checkpoints),
        text_variant=_text_variant(item.get("text_variant"), body),
        visual_variant=_dict_or_none(item.get("visual_variant")),
        audio_variant=_audio_variant(item.get("audio_variant"), body),
        interactive_variant=_interactive_variant(item.get("interactive_variant"), body),
        calculation_variant=calculation_variant,
        needs_review=needs_review,
        review_reasons=tuple(review_reasons),
    )


def _fallback_segments(
    source: str,
    *,
    sequence_offset: int,
) -> tuple[ParsedLessonSegment, ...]:
    parts = [part.strip() for part in re.split(r"\n{2,}", source) if part.strip()]
    if not parts:
        parts = [source.strip() or "Teacher review required."]
    segments: list[ParsedLessonSegment] = []
    for index, part in enumerate(parts[:80], start=1):
        sequence_order = sequence_offset + index
        content_type = _infer_content_type(part)
        modalities = _fallback_modalities(content_type, part)
        segments.append(
            ParsedLessonSegment(
                segment_key=f"fallback-{sequence_order}",
                content_type=content_type,
                sequence_order=sequence_order,
                title=_fallback_title(part, sequence_order),
                body=part,
                available_modalities=modalities,
                comprehension_checkpoints=(
                    {
                        "prompt": "What is the main idea in this part?",
                        "position": "after_segment",
                    },
                ),
                text_variant={"body": part},
                audio_variant=_placeholder_audio_variant(part),
                interactive_variant=_practice_variant(part)
                if content_type is LessonContentType.PRACTICE_QUESTION
                else None,
                needs_review=True,
                review_reasons=("deterministic_parse_used",),
            )
        )
    return tuple(segments)


WORDS_READ_PER_MINUTE = 130
"""Deliberately below adult silent-reading pace: these are school learners
working through new material, not skimming."""

MINUTES_BY_CONTENT_TYPE = {
    LessonContentType.PRACTICE_QUESTION: 3,
    LessonContentType.CALCULATION: 3,
    LessonContentType.WORKED_EXAMPLE: 2,
}
"""Floor for segments whose cost is the thinking, not the reading."""


def estimate_segment_minutes(segment: ParsedLessonSegment) -> int:
    """Rough minutes to work through one segment.

    Reading time from word count, floored per content type so a two-line
    practice question is not billed at zero minutes. An estimate for planning,
    not a measurement — the review screen presents it as approximate.
    """
    words = len(segment.body.split())
    reading = math.ceil(words / WORDS_READ_PER_MINUTE) if words else 0
    floor = MINUTES_BY_CONTENT_TYPE.get(segment.content_type, 1)
    checkpoints = len(segment.comprehension_checkpoints)
    return max(reading + checkpoints, floor)


def _normalize_segment(segment: ParsedLessonSegment) -> ParsedLessonSegment:
    reasons = list(segment.review_reasons)
    needs_review = segment.needs_review
    modalities = tuple(dict.fromkeys(segment.available_modalities))
    visual_variant = segment.visual_variant
    if ContentModality.VISUAL in modalities and not _has_visual_delivery(segment):
        visual_variant = None
        modalities = tuple(
            modality for modality in modalities if modality is not ContentModality.VISUAL
        )
        needs_review = True
        reasons.append("visual_variant_image_generation_failed")
    audio_variant = segment.audio_variant
    if ContentModality.AUDIO in modalities and not _has_audio_delivery(audio_variant):
        audio_variant = None
        modalities = tuple(
            modality for modality in modalities if modality is not ContentModality.AUDIO
        )
        needs_review = True
        reasons.append("audio_generation_failed")
    if segment.content_type is LessonContentType.CALCULATION:
        modalities = tuple(
            modality
            for modality in (ContentModality.INTERACTIVE, ContentModality.VISUAL)
            if (modality is ContentModality.INTERACTIVE and segment.calculation_variant is not None)
            or (modality is ContentModality.VISUAL and _has_visual_delivery(segment))
        )
        if segment.calculation_variant is None:
            # Without the co-construction this is not a calculation any more,
            # whatever else survived. It used to fall back only when nothing
            # at all was left, so a rejected variant that still had a picture
            # went out as a lone image: a child got a diagram of a sum and no
            # words. The text is always there, so give it back.
            modalities = (ContentModality.TEXT, *modalities)
            if _has_audio_delivery(audio_variant):
                modalities = (*modalities, ContentModality.AUDIO)
            needs_review = True
            reasons.append("calculation_segment_has_no_interactive_delivery")
    elif ContentModality.TEXT not in modalities:
        modalities = (ContentModality.TEXT, *modalities)
    if len(modalities) < 2:
        needs_review = True
        reasons.append("fewer_than_two_modalities")
    return ParsedLessonSegment(
        segment_key=segment.segment_key,
        content_type=segment.content_type,
        sequence_order=segment.sequence_order,
        title=segment.title,
        body=segment.body,
        available_modalities=modalities,
        comprehension_checkpoints=segment.comprehension_checkpoints,
        text_variant=segment.text_variant or {"body": segment.body},
        visual_variant=visual_variant,
        audio_variant=audio_variant,
        interactive_variant=segment.interactive_variant,
        calculation_variant=segment.calculation_variant,
        needs_review=needs_review,
        review_reasons=tuple(dict.fromkeys(reasons)),
        estimated_minutes=segment.estimated_minutes or estimate_segment_minutes(segment),
    )


def _has_visual_delivery(segment: ParsedLessonSegment) -> bool:
    if segment.content_type is LessonContentType.CALCULATION and segment.calculation_variant:
        return True
    return _is_generated_image_variant(segment.visual_variant)


def _is_generated_image_variant(value: dict[str, object] | None) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("type") != AI_GENERATED_IMAGE_TYPE:
        return False
    required = ("imageUrl", "prompt", "provider", "generatedAt")
    return all(isinstance(value.get(field), str) and value.get(field) for field in required)


def _has_audio_delivery(value: dict[str, object] | None) -> bool:
    return bool(isinstance(value, dict) and str(value.get("audioUrl") or "").strip())


def _step_answer(value: object) -> str | int | float | bool | None:
    """What this step is answered with, left in the type the model sent.

    A numeric step answered "3000" and one answered 3000 are the same answer,
    and coercing either way loses something: quote a number and a client has
    to parse it back, stringify a fraction like "3/4" and it stops being one.
    """

    if isinstance(value, bool | int | float):
        return value
    text = str(value or "").strip()
    return text or None


def _manipulative(value: object) -> dict[str, object] | None:
    """What a drag step gives a learner to move, if the model described one.

    Refused rather than half-accepted: a fraction bar cut into no pieces, or
    into a shape we have no renderer for, is worse on screen than a step that
    asks the child to type.
    """

    if not isinstance(value, dict):
        return None
    kinds = {kind.value for kind in ManipulativeKind}
    kind = str(value.get("kind") or "").strip()
    if kind not in kinds:
        return None
    try:
        parts = int(value.get("parts") or 0)
        rows = int(value.get("rows") or 1)
    except (TypeError, ValueError):
        return None
    if not 1 <= parts <= 100 or not 1 <= rows <= 20:
        return None
    return {
        "kind": kind,
        "parts": parts,
        "rows": rows,
        "labels": [str(item).strip() for item in _string_list(value.get("labels"))][:100],
    }


def _step_options(value: object) -> list[dict[str, object]]:
    """The choices a selection or drag step offers, in checkpoint shape."""

    if not isinstance(value, list):
        return []
    options: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        option_value = _step_answer(item.get("value"))
        label = str(item.get("label") or "").strip()
        if option_value is None or not label:
            continue
        options.append({"value": option_value, "label": label})
    return options


def _validated_calculation_variant(
    variant: dict[str, object],
) -> tuple[dict[str, object] | None, str | None]:
    # Say which check refused it. "malformed" named a category and no cause,
    # so two rejected co-constructions in a live lesson told nobody which of
    # four things had gone wrong, and the only way to find out was to guess.
    steps = variant.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        return None, "calculation_variant_too_few_steps"
    normalized_steps: list[dict[str, object]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            return None, "calculation_variant_malformed"
        prompt = str(step.get("prompt") or "").strip()
        expected_input = str(step.get("expectedInput") or "").strip()
        if not prompt:
            return None, "calculation_step_missing_prompt"
        if expected_input not in CALCULATION_INPUT_TYPES:
            # The single commonest way for this to fail: the model names a
            # gesture we do not have a renderer for.
            return None, "calculation_step_unknown_input_type"
        step_id = str(step.get("stepId") or f"step-{index}")
        hint = str(step.get("hint") or "").strip()
        step_answer = _step_answer(step.get("answer"))
        options = _step_options(step.get("options"))
        if step_answer is None:
            # A step that asks a child for something and does not say what the
            # something is cannot be marked, and a client has nothing to check
            # against. Better to reject the variant than ship a co-construction
            # that silently accepts anything.
            return None, "calculation_step_missing_answer"
        if expected_input in CHOICE_INPUT_TYPES and len(options) < 2:
            # Nothing to render. A selection step with no options is a prompt
            # with no way to answer it.
            return None, "calculation_step_missing_options"
        normalized_steps.append(
            {
                "stepId": step_id,
                "stepNumber": int(step.get("stepNumber") or index),
                "prompt": prompt,
                "expectedInput": expected_input,
                "hint": hint,
                "answer": step_answer,
                "options": options,
                "unit": str(step.get("unit") or "").strip() or None,
                "confirmationText": str(step.get("confirmationText") or "").strip(),
                "visualUpdate": str(step.get("visualUpdate") or "").strip(),
                "equationState": str(step.get("equationState") or "").strip(),
                "narrationAudio": _placeholder_step_narration(
                    step_id=step_id,
                    prompt=prompt,
                    hint=hint,
                ),
            }
        )
    manipulative = _manipulative(variant.get("manipulative"))
    if any(step["expectedInput"] == "drag" for step in normalized_steps) and manipulative is None:
        # A drag step with nothing to drag cannot be rendered, which is why
        # drag was being refused on generated content altogether.
        return None, "calculation_variant_missing_manipulative"
    answer = str(variant.get("answer") or "").strip()
    if not answer:
        # The contract carries an answer so a client never has to infer one
        # from the last step. Accepting a variant without it would put the
        # field on the wire and leave it permanently empty, which is worse
        # than not having it.
        return None, "calculation_variant_missing_answer"
    return {
        "type": "co_construction",
        "fullEquation": str(variant.get("fullEquation") or "").strip(),
        "manipulative": manipulative,
        "answer": answer,
        "steps": normalized_steps,
        "scaffoldImage": _dict_or_none(variant.get("scaffoldImage")),
        "completionStatement": str(variant.get("completionStatement") or "").strip(),
    }, None


def _modalities(value: object) -> tuple[ContentModality, ...]:
    if not isinstance(value, list):
        return (ContentModality.TEXT, ContentModality.AUDIO)
    parsed: list[ContentModality] = []
    for item in value:
        try:
            parsed.append(ContentModality(str(item)))
        except ValueError:
            continue
    return tuple(parsed) or (ContentModality.TEXT, ContentModality.AUDIO)


def _content_type(value: str) -> LessonContentType:
    try:
        return LessonContentType(value)
    except ValueError:
        return LessonContentType.EXPLANATORY_TEXT


def _infer_content_type(text: str) -> LessonContentType:
    lowered = text.casefold()
    if any(marker in lowered for marker in ("solve", "calculate", "=", "+", "-")):
        return LessonContentType.PRACTICE_QUESTION
    if "example" in lowered:
        return LessonContentType.WORKED_EXAMPLE
    if lowered.startswith(("define", "definition")):
        return LessonContentType.DEFINITION
    if "summary" in lowered:
        return LessonContentType.SUMMARY
    return LessonContentType.EXPLANATORY_TEXT


def _fallback_modalities(
    content_type: LessonContentType,
    text: str,
) -> tuple[ContentModality, ...]:
    if content_type is LessonContentType.PRACTICE_QUESTION:
        return (ContentModality.TEXT, ContentModality.INTERACTIVE)
    if any(word in text.casefold() for word in ("diagram", "chart", "graph")):
        return (ContentModality.TEXT, ContentModality.VISUAL)
    return (ContentModality.TEXT, ContentModality.AUDIO)


def _fallback_title(text: str, sequence_order: int) -> str:
    first_line = text.splitlines()[0].strip()
    if len(first_line) <= 80:
        return first_line
    return f"Segment {sequence_order}"


def _audio_variant(value: object, body: str) -> dict[str, object] | None:
    if isinstance(value, dict):
        script = str(value.get("script") or body[:700]).strip()
        return {
            "script": script,
            "audioUrl": str(value.get("audioUrl") or ""),
            "durationMs": _duration_ms(value.get("durationMs")),
            "provider": str(value.get("provider") or "tts_provider_tbd"),
        }
    return _placeholder_audio_variant(body)


def _text_variant(value: object, body: str) -> dict[str, object]:
    """The text modality. Its body is the segment's body, always.

    These were two independently settable strings. The model could return a
    text_variant.body of its own and it would win, and then the teacher's
    review screen - which reads text_variant.body - and the student player -
    which reads segment.body - would be showing different words. A teacher
    would have approved text no child ever saw, and the approval gate would
    have been guarding the wrong string.

    It has never happened, because nothing asks the model for a separate one,
    so every segment in the library has the two identical. That is luck rather
    than a guarantee, and one prompt change away from not being true. So the
    override is refused here: there is one text, and text_variant.body is a
    view onto it for clients that read the variant.

    keyPoints are highlights that sit beside the body, not a shorter retelling
    of it - so a point that simply restates the whole body is dropped rather
    than shown twice.
    """

    source = value if isinstance(value, dict) else {}
    body = body.strip()
    points = []
    for point in _string_list(source.get("keyPoints")):
        stripped = point.strip()
        if stripped and stripped.casefold() != body.casefold():
            points.append(stripped)
    return {"body": body, "keyPoints": points[:6]}


def _interactive_variant(value: object, body: str) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    options = []
    raw_options = value.get("options")
    if isinstance(raw_options, list):
        for option in raw_options:
            if isinstance(option, dict) and "value" in option:
                options.append(
                    {
                        "value": option["value"],
                        "label": str(option.get("label") or option["value"]),
                    }
                )
            elif isinstance(option, (str, int, float, bool)):
                options.append({"value": option, "label": str(option)})
    answer_key = value.get("answerKey")
    if isinstance(answer_key, list):
        answer_key = [
            answer for answer in answer_key if isinstance(answer, (str, int, float, bool))
        ]
    elif not isinstance(answer_key, (str, int, float, bool, type(None))):
        answer_key = None
    instructions = value.get("instructions")
    return {
        "type": str(value.get("type") or "practice_problem"),
        "prompt": str(value.get("prompt") or body[:500]),
        "expectedInteraction": str(value.get("expectedInteraction") or "teacher_review"),
        "options": options,
        "answerKey": answer_key,
        "instructions": str(instructions) if instructions is not None else None,
    }


def _placeholder_audio_variant(body: str) -> dict[str, object]:
    return {
        "script": body[:700].strip(),
        "audioUrl": "",
        "durationMs": None,
        "provider": "tts_provider_tbd",
    }


def _placeholder_step_narration(
    *,
    step_id: str,
    prompt: str,
    hint: str,
) -> dict[str, object]:
    script = f"{prompt} {hint}".strip()
    return {
        "stepId": step_id,
        "script": script,
        "audioUrl": "",
        "durationMs": None,
        "provider": "tts_provider_tbd",
    }


def _practice_variant(text: str) -> dict[str, object]:
    return {
        "type": "practice_problem",
        "prompt": text[:500],
        "expectedInteraction": "teacher_review",
    }


def _dict_or_none(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


#: Long enough to be a title, short enough to sit in a list without wrapping.
MAX_TITLE_CHARS = 120


def _lesson_title(value: object) -> str | None:
    """The lesson's own name, if the parser gave one worth using.

    A title has to survive a teacher's library list, so a sentence the model
    wrote about the lesson is no better than the filename it replaces.
    """

    title = _optional_string(value)
    if title is None:
        return None
    title = " ".join(title.split())
    if not title or len(title) > MAX_TITLE_CHARS:
        return None
    return title


def _review_reasons(value: object) -> list[str]:
    """Keep the reasons the console has copy for, and no others.

    The model is asked to flag segments for review and answers in its own
    words - a whole sentence about practice questions needing audio, say. The
    column takes it, because it is JSON; the response model does not, because
    it is an enum, so the sentence made the lesson unreadable and every read
    of it a 500. A reason the console cannot render is not a reason it can
    show anyone, so an unrecognised one becomes the fact that the model wanted
    a human to look, which is the part that matters.
    """

    known = {reason.value for reason in SegmentReviewReason}
    reasons: list[str] = []
    for reason in _string_list(value):
        reasons.append(
            reason if reason in known else SegmentReviewReason.MODEL_FLAGGED_FOR_REVIEW.value
        )
    return list(dict.fromkeys(reasons))


def _string_list(value: object) -> Iterable[str]:
    if not isinstance(value, list):
        return ()
    return (str(item) for item in value if str(item).strip())


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _confirmation_summary(segments: list[ParsedLessonSegment]) -> str:
    return (
        f"Parsed {len(segments)} lesson segment"
        f"{'' if len(segments) == 1 else 's'} for teacher review."
    )
