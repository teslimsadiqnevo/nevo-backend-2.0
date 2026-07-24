import json
import re
from collections.abc import Iterable
from uuid import UUID

from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.errors import AiGatewayError
from nevo.ai_gateway.service import AiGatewayService
from nevo.content_parsing.entities import (
    ContentParseRequest,
    ParsedLesson,
    ParsedLessonSegment,
    SourcePage,
    StoredParsedLesson,
)
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    LessonContentType,
    LessonSourceType,
)

MAX_CHUNK_CHARS = 24_000
PROMPT_NAME = "content_parse.default"
CALCULATION_INPUT_TYPES = {"selection", "numeric", "text", "drag"}


class ContentParsingService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyContentParsingRepository,
        ai_gateway: AiGatewayService,
    ) -> None:
        self._repository = repository
        self._ai_gateway = ai_gateway

    async def parse(
        self,
        *,
        request: ContentParseRequest,
        requested_by_user_id: UUID,
    ) -> StoredParsedLesson:
        source = _source_for_prompt(request)
        chunks = _chunks(source)
        segments: list[ParsedLessonSegment] = []
        review_notes: list[dict[str, object]] = []
        gemini_call_count = 0

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
                        max_output_tokens=4_096,
                    )
                )
                gemini_call_count += 1
                segments.extend(
                    _segments_from_gemini(
                        result.text,
                        sequence_offset=len(segments),
                    )
                )
            except (AiGatewayError, ValueError, json.JSONDecodeError) as error:
                review_notes.append(
                    {
                        "code": "gemini_parse_fallback",
                        "chunkNumber": index,
                        "message": (
                            "This chunk used deterministic parsing because Gemini "
                            "could not return valid structured lesson data."
                        ),
                        "error": error.__class__.__name__,
                    }
                )
                segments.extend(
                    _fallback_segments(
                        chunk,
                        sequence_offset=len(segments),
                    )
                )

        parsed = ParsedLesson(
            title=request.title,
            segments=tuple(_normalize_segment(segment) for segment in segments),
            review_notes=tuple(review_notes),
            confirmation_summary=_confirmation_summary(segments),
            gemini_call_count=gemini_call_count,
            chunk_count=len(chunks),
        )
        return await self._repository.store(
            request=request,
            parsed=parsed,
            requested_by_user_id=requested_by_user_id,
        )


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


def _segments_from_gemini(
    text: str,
    *,
    sequence_offset: int,
) -> tuple[ParsedLessonSegment, ...]:
    payload = _json_payload(text)
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("Gemini returned no parseable segments")
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
        raise ValueError("Gemini returned only malformed segments")
    return tuple(parsed)


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
        raise ValueError("Gemini payload must be a JSON object")
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
    raw_modalities = item.get("availableModalities") or item.get(
        "available_modalities"
    )
    modalities = _modalities(raw_modalities)
    calculation_variant = _dict_or_none(item.get("calculation_variant"))
    review_reasons = list(_string_list(item.get("review_reasons")))
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
        item.get("comprehension_checkpoints")
        or item.get("comprehensionCheckpoints")
    )
    return ParsedLessonSegment(
        segment_key=str(item.get("segment_key") or f"segment-{sequence_order}"),
        content_type=content_type,
        sequence_order=sequence_order,
        title=_optional_string(item.get("title")),
        body=body,
        available_modalities=modalities,
        comprehension_checkpoints=tuple(checkpoints),
        text_variant=_dict_or_none(item.get("text_variant")),
        visual_variant=_dict_or_none(item.get("visual_variant")),
        audio_variant=_audio_variant(item.get("audio_variant"), body),
        interactive_variant=_dict_or_none(item.get("interactive_variant")),
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


def _normalize_segment(segment: ParsedLessonSegment) -> ParsedLessonSegment:
    reasons = list(segment.review_reasons)
    needs_review = segment.needs_review
    modalities = tuple(dict.fromkeys(segment.available_modalities))
    if segment.content_type is LessonContentType.CALCULATION:
        modalities = (ContentModality.INTERACTIVE, ContentModality.VISUAL)
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
        visual_variant=segment.visual_variant,
        audio_variant=segment.audio_variant,
        interactive_variant=segment.interactive_variant,
        calculation_variant=segment.calculation_variant,
        needs_review=needs_review,
        review_reasons=tuple(dict.fromkeys(reasons)),
    )


def _validated_calculation_variant(
    variant: dict[str, object],
) -> tuple[dict[str, object] | None, str | None]:
    steps = variant.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        return None, "calculation_variant_malformed"
    normalized_steps: list[dict[str, object]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            return None, "calculation_variant_malformed"
        prompt = str(step.get("prompt") or "").strip()
        expected_input = str(step.get("expectedInput") or "").strip()
        if not prompt or expected_input not in CALCULATION_INPUT_TYPES:
            return None, "calculation_variant_malformed"
        step_id = str(step.get("stepId") or f"step-{index}")
        hint = str(step.get("hint") or "").strip()
        normalized_steps.append(
            {
                "stepId": step_id,
                "stepNumber": int(step.get("stepNumber") or index),
                "prompt": prompt,
                "expectedInput": expected_input,
                "hint": hint,
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
    return {
        "type": "co_construction",
        "fullEquation": str(variant.get("fullEquation") or "").strip(),
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
            "durationMs": int(value.get("durationMs") or 0),
            "provider": str(value.get("provider") or "tts_provider_tbd"),
        }
    return _placeholder_audio_variant(body)


def _placeholder_audio_variant(body: str) -> dict[str, object]:
    return {
        "script": body[:700].strip(),
        "audioUrl": "",
        "durationMs": 0,
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
        "durationMs": 0,
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
