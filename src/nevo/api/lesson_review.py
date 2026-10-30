"""The review a teacher has to perform before a lesson can be assigned.

The product told a teacher that parts of a lesson needed review and then gave
them nothing to review with: key points rendered as cards that could not be
opened, no source text behind them, and no accept, amend or remove anywhere.
Assignment stayed refused, which blocked the one action the product is sold
on.

Two rulings shape what is here. Only points Nevo could not ground in the
segment they came from are outstanding, so a teacher never clicks through a
whole lesson to assign it. And what a teacher writes is kept beside what Nevo
extracted rather than over it, so the screen can always show both.
"""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nevo.ai_gateway.errors import AiGatewayError
from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.safety import POLICY_VERSION
from nevo.api.ai_gateway import AiGatewayDependency, public_ai_error
from nevo.api.auth import PrincipalDependency
from nevo.api.casing import CAMEL_CONFIG
from nevo.api.lesson_contracts import GuidedCheckStep, depth_approved, explanation_reveals_answer
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor
from nevo.api.response_models import CamelResponse
from nevo.content_parsing.media_contracts import LessonMediaResponse
from nevo.content_parsing.depth import DepthVariantError, _json_payload
from nevo.db.models.account import User
from nevo.db.models.ai_gateway import AiGatewayCall
from nevo.db.models.content import Lesson, LessonKeyPoint, LessonSegment
from nevo.db.models.deferred_media import DeferredLessonMedia
from nevo.db.models.lesson_signoff import LessonReviewSignoff
from nevo.domain.intelligence.vocabulary import KeyPointConfidence, KeyPointReviewState
from nevo.domain.ai_gateway.vocabulary import AiService

router = APIRouter(prefix="/api/v1", tags=["learning product"])

REVIEW_ROLES = {"teacher", "senco_admin", "other_admin"}

#: The states that mean a person has dealt with this point.
RESOLVED_STATES = {
    KeyPointReviewState.ACCEPTED,
    KeyPointReviewState.AMENDED,
    KeyPointReviewState.REMOVED,
}


class KeyPointResponse(CamelResponse):
    """One key point, and everything the card needs when it is expanded."""

    id: UUID
    segment_id: UUID
    segment_title: str | None
    position: int
    #: What the lesson says now: the teacher's wording where they wrote one.
    text: str
    #: What Nevo read, kept even after a teacher rewrites it.
    extracted_text: str
    #: The teacher's wording, or null if they have not written one.
    amended_text: str | None
    #: The segment text this was drawn from, as it was when it was drawn.
    source_text: str
    confidence: KeyPointConfidence
    review_state: KeyPointReviewState
    #: True while this point is what stands between the lesson and a class.
    outstanding: bool
    resolved_at: datetime | None
    resolved_by: UUID | None


class ReviewSignoffResponse(CamelResponse):
    id: UUID
    kind: Literal["key_points", "rewrites", "guided_steps", "checks", "calculation_parts"]
    approved_by: UUID | None
    approved_by_name: str
    approved_at: datetime
    content_hash: str
    current: bool


class GuidedStepsReviewItem(CamelResponse):
    segment_id: UUID
    segment_title: str | None
    question_id: str
    question_prompt: str
    question_answer_type: str | None = None
    question_options: list[dict[str, object]] = Field(default_factory=list)
    question_answer_key: object | None = None
    review_status: Literal["pending_review", "approved"]
    guided_questions: list[str] = Field(default_factory=list)
    steps: list[GuidedCheckStep]
    answer_leakage_step_ids: list[str] = Field(default_factory=list)


class CalculationPartsReviewItem(CamelResponse):
    segment_id: UUID
    segment_title: str | None
    step_id: str
    prompt: str
    parts: list[str]
    review_status: Literal["pending_review", "approved"]


class CheckReviewItem(CamelResponse):
    segment_id: UUID | None
    scope: Literal["checkpoint", "assessment"] = "checkpoint"
    segment_title: str | None
    question_id: str
    question_prompt: str
    question_answer_type: str
    question_options: list[dict[str, object]] = Field(default_factory=list)
    question_answer_key: object
    mastery_level: Literal["knowledge", "application", "analysis"] | None = None
    mastery_level_authored_by: Literal["person", "nevo"] | None = None
    teacher_reviewed: bool = False
    markable: bool = True


class LessonReviewResponse(CamelResponse):
    lesson_id: UUID
    title: str
    outstanding_count: int
    key_point_count: int
    ready_to_assign: bool
    key_points: list[KeyPointResponse]
    key_points_content_hash: str = ""
    rewrites_content_hash: str = ""
    key_point_approval: ReviewSignoffResponse | None = None
    rewrite_approval: ReviewSignoffResponse | None = None
    guided_steps_approval: ReviewSignoffResponse | None = None
    calculation_parts_approval: ReviewSignoffResponse | None = None
    calculation_parts_content_hash: str = ""
    calculation_parts: list[CalculationPartsReviewItem] = Field(default_factory=list)
    checks_approval: ReviewSignoffResponse | None = None
    checks_content_hash: str = ""
    checks: list[CheckReviewItem] = Field(default_factory=list)
    guided_steps_content_hash: str = ""
    guided_steps: list[GuidedStepsReviewItem] = Field(default_factory=list)
    pending_guided_step_count: int = 0
    missing_key_point_segment_ids: list[UUID] = Field(default_factory=list)
    rewrite_count: int = 0
    pending_rewrite_count: int = 0
    review_complete: bool = False
    media: LessonMediaResponse | None = None


class GuidedStepsBulkReviewRequest(BaseModel):
    model_config = CAMEL_CONFIG

    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CalculationPartsGenerationResponse(CamelResponse):
    lesson_id: UUID
    generated_step_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    review: "LessonReviewResponse"


@router.post(
    "/lessons/{lesson_id}/calculation-parts/generate",
    response_model=CalculationPartsGenerationResponse,
)
async def generate_calculation_parts(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
    gateway: AiGatewayDependency,
):
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segments = list(await session.scalars(select(LessonSegment).where(
        LessonSegment.lesson_id == lesson.id,
    ).order_by(LessonSegment.sequence_order).with_for_update()))
    tokens_in = tokens_out = generated = 0
    cost = 0
    for segment in segments:
        variant = segment.calculation_variant or {}
        eligible = [step for step in variant.get("steps", [])
                    if not step.get("parts") and not step.get("pendingParts")]
        if not eligible:
            continue
        result = await gateway.generate(AiGenerationRequest(
            requester_user_id=actor.id,
            service=AiService.LESSON_GENERATION,
            prompt_name="calculation_parts.default",
            variables={
                "source_text": segment.body[:8000],
                "steps_json": json.dumps([{
                    "stepId": step.get("stepId"), "prompt": step.get("prompt"),
                    "answer": step.get("answer"), "hint": step.get("hint"),
                } for step in eligible]),
            },
            max_output_tokens=2048,
            timeout_seconds=90,
            json_output=True,
        ))
        if result.fallback_used or result.stop_reason == "max_tokens":
            raise HTTPException(503, detail={"code": "calculation_parts_generation_unavailable"})
        try:
            payload = _json_payload(result.text)
            proposals = payload["steps"]
            if not isinstance(proposals, list):
                raise ValueError
            by_id = {str(item["stepId"]): item["parts"] for item in proposals}
            if len(by_id) != len(proposals):
                raise ValueError
            allowed = {str(step.get("stepId")) for step in eligible}
            if not set(by_id).issubset(allowed):
                raise ValueError
            for parts in by_id.values():
                if not isinstance(parts, list) or len(parts) > 8 or any(
                    not isinstance(part, str) or not part.strip() or len(part) > 300
                    for part in parts
                ):
                    raise ValueError
        except (ValueError, KeyError, TypeError, DepthVariantError):
            raise HTTPException(502, detail={"code": "calculation_parts_invalid_output"}) from None
        updated = []
        for raw in variant["steps"]:
            step = dict(raw)
            parts = by_id.get(str(step.get("stepId")), [])
            if len(parts) >= 2:
                step["pendingParts"] = [part.strip() for part in parts]
                step["partsReviewStatus"] = "pending_review"
                generated += 1
            updated.append(step)
        segment.calculation_variant = {**variant, "steps": updated}
        audit = await session.get(AiGatewayCall, result.call_id)
        if audit:
            cost += audit.estimated_cost_usd
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
    await session.commit()
    return CalculationPartsGenerationResponse(
        lesson_id=lesson.id, generated_step_count=generated,
        input_tokens=tokens_in, output_tokens=tokens_out,
        estimated_cost_usd=str(cost), review=await _review_result(session, lesson),
    )


@router.post(
    "/lessons/{lesson_id}/calculation-parts/approve-all",
    response_model=LessonReviewResponse,
)
async def approve_calculation_parts(
    lesson_id: UUID,
    payload: GuidedStepsBulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segments = list(await session.scalars(select(LessonSegment).where(
        LessonSegment.lesson_id == lesson.id,
    ).order_by(LessonSegment.sequence_order).with_for_update()))
    material, _ = _calculation_parts_material(segments)
    digest = _hash(material)
    if digest != payload.expected_content_hash:
        raise HTTPException(409, detail={"code": "review_content_changed"})
    pending = any(step.get("pendingParts") for segment in segments
                  for step in (segment.calculation_variant or {}).get("steps", []))
    if not pending:
        raise HTTPException(409, detail={"code": "no_calculation_parts_to_approve"})
    now = datetime.now(UTC)
    reviewer_name = " ".join(part for part in (actor.first_name, actor.last_name) if part)
    session.add(LessonReviewSignoff(
        lesson_id=lesson.id, kind="calculation_parts", approved_by=actor.id,
        approved_by_name=reviewer_name or actor.email or str(actor.id),
        approved_at=now, content_hash=digest, content_snapshot=material,
    ))
    for segment in segments:
        variant = segment.calculation_variant or {}
        if not variant:
            continue
        changed = False
        steps = []
        for raw in variant.get("steps", []):
            step = dict(raw)
            parts = step.pop("pendingParts", None)
            if parts:
                step["parts"] = parts
                step["partsReviewStatus"] = "approved"
                changed = True
            steps.append(step)
        if changed:
            segment.calculation_variant = {**variant, "steps": steps}
    await session.commit()
    return await _review_result(session, lesson)


class KeyPointAmendment(BaseModel):
    model_config = CAMEL_CONFIG

    text: Annotated[str, Field(min_length=1, max_length=400)]


async def _key_point_rows(
    session: AsyncSession,
    lesson_id: UUID,
) -> list[tuple[LessonKeyPoint, str | None]]:
    rows = await session.execute(
        select(LessonKeyPoint, LessonSegment.title)
        .join(LessonSegment, LessonSegment.id == LessonKeyPoint.segment_id)
        .where(LessonKeyPoint.lesson_id == lesson_id)
        .order_by(LessonSegment.sequence_order, LessonKeyPoint.position)
    )
    return [(point, title) for point, title in rows.all()]


def _view(point: LessonKeyPoint, segment_title: str | None) -> KeyPointResponse:
    return KeyPointResponse(
        id=point.id,
        segment_id=point.segment_id,
        segment_title=segment_title,
        position=point.position,
        text=point.text,
        extracted_text=point.extracted_text,
        amended_text=point.amended_text,
        source_text=point.source_text,
        confidence=point.confidence,
        review_state=point.review_state,
        outstanding=point.review_state is KeyPointReviewState.UNSURE,
        resolved_at=point.resolved_at,
        resolved_by=point.resolved_by,
    )


def _review(
    lesson: Lesson,
    rows: list[tuple[LessonKeyPoint, str | None]],
) -> LessonReviewResponse:
    views = [_view(point, title) for point, title in rows]
    outstanding = sum(1 for view in views if view.outstanding)
    return LessonReviewResponse(
        lesson_id=lesson.id,
        title=lesson.title,
        outstanding_count=outstanding,
        key_point_count=len(views),
        ready_to_assign=outstanding == 0,
        key_points=views,
    )


async def _lesson_for_review(
    session: AsyncSession,
    principal: PrincipalDependency,
    lesson_id: UUID,
) -> tuple[Lesson, User]:
    actor = await require_school_actor(session, principal, roles=REVIEW_ROLES)
    lesson = await session.get(Lesson, lesson_id, with_for_update=True)
    if lesson is None or lesson.school_id != actor.school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    return lesson, actor


async def _point_for_review(
    session: AsyncSession,
    lesson: Lesson,
    key_point_id: UUID,
) -> LessonKeyPoint:
    point = await session.get(LessonKeyPoint, key_point_id)
    if point is None or point.lesson_id != lesson.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key point not found")
    return point


def _resolve(point: LessonKeyPoint, *, state: KeyPointReviewState, actor: User) -> None:
    point.review_state = state
    point.resolved_at = datetime.now(UTC)
    point.resolved_by = actor.id


@router.get("/lessons/{lesson_id}/review", response_model=LessonReviewResponse)
async def read_lesson_review(
    lesson_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """Everything the lesson page's needs-review state renders.

    One read rather than one per card: the screen shows the cards and the
    remaining count together, and a teacher opening a card should not cost a
    request to find out what Nevo read.
    """

    lesson, _ = await _lesson_for_review(session, principal, lesson_id)
    return await _review_result(session, lesson)


@router.post(
    "/lessons/{lesson_id}/key-points/{key_point_id}/accept",
    response_model=LessonReviewResponse,
    deprecated=True,
)
async def accept_key_point(
    lesson_id: UUID,
    key_point_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """A teacher read the point and let it stand."""

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    point = await _point_for_review(session, lesson, key_point_id)
    if point.review_state not in RESOLVED_STATES:
        _resolve(point, state=KeyPointReviewState.ACCEPTED, actor=actor)
        await session.commit()
    return await _review_result(session, lesson)


@router.patch(
    "/lessons/{lesson_id}/key-points/{key_point_id}",
    response_model=LessonReviewResponse,
)
async def amend_key_point(
    lesson_id: UUID,
    key_point_id: UUID,
    payload: KeyPointAmendment,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """A teacher rewrote the point.

    The new wording goes in the segment the child reads as well, because a key
    point a teacher corrected and a child still sees the old version of is
    worse than no correction.
    """

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    point = await _point_for_review(session, lesson, key_point_id)
    if point.text != payload.text.strip():
        await _invalidate_signoffs(session, lesson.id, "key_points")
    point.amended_text = payload.text.strip()
    _resolve(point, state=KeyPointReviewState.AMENDED, actor=actor)
    await _write_through(session, point)
    await session.commit()
    return await _review_result(session, lesson)


@router.delete(
    "/lessons/{lesson_id}/key-points/{key_point_id}",
    response_model=LessonReviewResponse,
)
async def remove_key_point(
    lesson_id: UUID,
    key_point_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """A teacher took the point out of the lesson.

    The row stays, marked removed. A deleted row would lose the fact that Nevo
    read something a teacher rejected, which is the record that says whether
    the parser is getting better.
    """

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    point = await _point_for_review(session, lesson, key_point_id)
    if point.review_state != KeyPointReviewState.REMOVED:
        await _invalidate_signoffs(session, lesson.id, "key_points")
    _resolve(point, state=KeyPointReviewState.REMOVED, actor=actor)
    await _write_through(session, point)
    await session.commit()
    return await _review_result(session, lesson)


async def _write_through(session: AsyncSession, point: LessonKeyPoint) -> None:
    """Put the teacher's decision into the variant a child is served."""

    segment = await session.get(LessonSegment, point.segment_id)
    if segment is None:
        return
    points = await session.scalars(
        select(LessonKeyPoint)
        .where(LessonKeyPoint.segment_id == point.segment_id)
        .order_by(LessonKeyPoint.position)
    )
    kept = [item.text for item in points if item.review_state is not KeyPointReviewState.REMOVED]
    segment.text_variant = {**(segment.text_variant or {}), "keyPoints": kept}


class BulkReviewRequest(BaseModel):
    model_config = CAMEL_CONFIG

    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class MissingKeyPointWrite(BaseModel):
    model_config = CAMEL_CONFIG

    action: Literal["add", "omit"]
    text: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def valid_text(self):
        self.text = self.text.strip() if self.text is not None else None
        if self.action == "add" and not self.text:
            raise ValueError("Write a key point before adding it.")
        if self.action == "omit" and self.text:
            raise ValueError("Omitting a key point does not take text.")
        return self


class RewriteEdit(BaseModel):
    body: str = Field(min_length=1, max_length=50000)

    @field_validator("body")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Rewrite wording cannot be blank.")
        return value


def _hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def _calculation_parts_material(segments):
    material, views = [], []
    for segment in segments:
        for step in (segment.calculation_variant or {}).get("steps", []):
            parts = step.get("pendingParts") or step.get("parts") or []
            state = step.get("partsReviewStatus")
            if not parts or state not in {"pending_review", "approved"}:
                continue
            item = {
                "segmentId": str(segment.id),
                "stepId": str(step.get("stepId")),
                "prompt": str(step.get("prompt")),
                "parts": parts,
            }
            material.append(item)
            views.append(CalculationPartsReviewItem(
                segment_id=segment.id, segment_title=segment.title,
                step_id=item["stepId"], prompt=item["prompt"], parts=parts,
                review_status=state,
            ))
    return material, views


def _current_signoff(record, material):
    if record.invalidated_at is not None:
        return False
    if record.content_hash == _hash(material):
        return True
    if record.kind == "key_points" and isinstance(record.content_snapshot, list):
        return [item for item in record.content_snapshot if "mediaId" not in item] == material
    return False


async def _invalidate_signoffs(session, lesson_id, kind):
    await session.execute(
        update(LessonReviewSignoff)
        .where(
            LessonReviewSignoff.lesson_id == lesson_id,
            LessonReviewSignoff.kind == kind,
            LessonReviewSignoff.invalidated_at.is_(None),
        )
        .values(invalidated_at=datetime.now(UTC))
    )


async def _review_material(session, lesson):
    rows = await _key_point_rows(session, lesson.id)
    segments = list(
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson.id)
            .order_by(LessonSegment.sequence_order, LessonSegment.id)
        )
    )
    points = [
        {
            "id": str(point.id),
            "segmentId": str(point.segment_id),
            "text": point.text,
            "source": point.source_text,
            "omitted": point.review_state == KeyPointReviewState.REMOVED,
        }
        for point, _ in rows
    ]
    sources = [{"segmentId": str(segment.id), "body": segment.body} for segment in segments]
    key_material = [*sources, *points]
    rewrites = []
    for segment in segments:
        for kind in ("simplified", "expanded"):
            item = (segment.depth_variants or {}).get(kind)
            if isinstance(item, dict) and item.get("body"):
                rewrites.append(
                    {
                        "segmentId": str(segment.id),
                        "kind": kind,
                        "body": item["body"],
                        "source": segment.body,
                    }
                )
    return rows, segments, key_material, rewrites


def _checks_material(segments, assessment=None):
    from nevo.api.lesson_contracts import checkpoint_payloads

    material = []
    views = []
    for segment in [*segments, None] if assessment else segments:
        questions = checkpoint_payloads(
            assessment if segment is None else segment.comprehension_checkpoints or [],
            segment_key="lesson-assessment" if segment is None else segment.segment_key,
        )
        for question in questions:
            item = {
                "segmentId": str(segment.id) if segment is not None else None,
                "questionId": str(question["id"]),
                "questionPrompt": question["prompt"],
                "questionAnswerType": question["answerType"],
                "questionOptions": question.get("options") or [],
                "questionAnswerKey": question["answerKey"],
            }
            if segment is None:
                item["scope"] = "assessment"
            if question.get("masteryLevel") is not None:
                item["masteryLevel"] = question["masteryLevel"]
                item["masteryLevelAuthoredBy"] = question.get("masteryLevelAuthoredBy")
            authored = question.get("authoredBy") == "person"
            inferred_level = (
                item.get("masteryLevel") is not None
                and item.get("masteryLevelAuthoredBy") != "person"
            )
            markable = bool(item["questionPrompt"] and item["questionAnswerKey"] is not None)
            if (not authored or inferred_level) and markable:
                material.append(item)
            views.append(CheckReviewItem(
                segment_id=segment.id if segment is not None else None,
                segment_title=segment.title if segment is not None else None,
                scope=item.get("scope", "checkpoint"),
                question_id=item["questionId"], question_prompt=item["questionPrompt"],
                question_answer_type=item["questionAnswerType"],
                question_options=item["questionOptions"], question_answer_key=item["questionAnswerKey"],
                mastery_level=item.get("masteryLevel"),
                mastery_level_authored_by=item.get("masteryLevelAuthoredBy"),
                teacher_reviewed=authored and not inferred_level and markable,
                markable=markable,
            ))
    return material, views


async def approved_check_ids(session, lesson_id):
    from nevo.api.lesson_contracts import checkpoint_payloads
    lesson = await session.get(Lesson, lesson_id)
    segments = list(await session.scalars(
        select(LessonSegment).where(LessonSegment.lesson_id == lesson_id)
        .order_by(LessonSegment.sequence_order, LessonSegment.id)
    ))
    assessment = lesson.assessment or [] if lesson is not None else []
    material, _ = _checks_material(segments, assessment)
    authored = {
        (str(segment.id), str(question["id"]))
        for segment in segments
        for question in checkpoint_payloads(
            segment.comprehension_checkpoints or [], segment_key=segment.segment_key
        )
        if question.get("authoredBy") == "person"
        and (question.get("masteryLevel") is None or question.get("masteryLevelAuthoredBy") == "person")
        and question.get("answerKey") is not None
    }
    authored.update(
        ("assessment", str(question["id"]))
        for question in checkpoint_payloads(assessment, segment_key="lesson-assessment")
        if question.get("authoredBy") == "person"
        and (question.get("masteryLevel") is None or question.get("masteryLevelAuthoredBy") == "person")
        and question.get("answerKey") is not None
    )
    if not material:
        return authored
    approval = await session.scalar(
        select(LessonReviewSignoff).where(
            LessonReviewSignoff.lesson_id == lesson_id,
            LessonReviewSignoff.kind == "checks",
            LessonReviewSignoff.invalidated_at.is_(None),
        ).order_by(LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc()).limit(1)
    )
    if approval is None or approval.content_hash != _hash(material):
        return authored
    return authored | {(
        item["segmentId"] or "assessment", item["questionId"]
    ) for item in material}


def _guided_steps_material(segments):
    material = []
    views = []
    pending_count = 0
    for segment in segments:
        for question in segment.comprehension_checkpoints or []:
            state = question.get("guidedStepsReviewStatus")
            steps = question.get("pendingGuidedSteps") or question.get("guidedSteps") or []
            guided_questions = [
                str(value).strip()
                for value in question.get("guidedQuestions", [])
                if isinstance(value, str) and value.strip()
            ]
            if not steps or state not in {"pending_review", "approved"}:
                continue
            item = {
                "segmentId": str(segment.id),
                "questionId": str(question.get("id") or ""),
                "questionPrompt": str(question.get("prompt") or ""),
                "questionAnswerType": question.get("answerType"),
                "questionOptions": question.get("options") or [],
                "questionAnswerKey": question.get("answerKey"),
                "guidedQuestions": guided_questions,
                "steps": steps,
            }
            parsed_steps = [GuidedCheckStep.model_validate(step) for step in steps]
            material.append(item)
            views.append(
                GuidedStepsReviewItem(
                    segment_id=segment.id,
                    segment_title=segment.title,
                    question_id=item["questionId"],
                    question_prompt=item["questionPrompt"],
                    question_answer_type=item["questionAnswerType"],
                    question_options=item["questionOptions"],
                    question_answer_key=item["questionAnswerKey"],
                    review_status=state,
                    guided_questions=guided_questions,
                    steps=parsed_steps,
                    answer_leakage_step_ids=[
                        step.id
                        for step in parsed_steps
                        if explanation_reveals_answer(step)
                    ],
                )
            )
            if state == "pending_review":
                pending_count += len(steps)
    return material, views, pending_count


async def review_complete_map(session, lesson_ids):
    """Calculate library readiness without loading review media."""
    if not lesson_ids:
        return {}
    lessons = {
        lesson.id: lesson for lesson in await session.scalars(
            select(Lesson).where(Lesson.id.in_(lesson_ids))
        )
    }
    segments_by_lesson = defaultdict(list)
    for segment in await session.scalars(
        select(LessonSegment).where(LessonSegment.lesson_id.in_(lesson_ids))
        .order_by(LessonSegment.lesson_id, LessonSegment.sequence_order, LessonSegment.id)
    ):
        segments_by_lesson[segment.lesson_id].append(segment)
    points_by_lesson = defaultdict(list)
    for point in await session.scalars(
        select(LessonKeyPoint).join(LessonSegment, LessonSegment.id == LessonKeyPoint.segment_id)
        .where(LessonKeyPoint.lesson_id.in_(lesson_ids))
        .order_by(LessonKeyPoint.lesson_id, LessonSegment.sequence_order, LessonKeyPoint.position)
    ):
        points_by_lesson[point.lesson_id].append(point)
    approvals_by_lesson = defaultdict(dict)
    for record in await session.scalars(
        select(LessonReviewSignoff).where(LessonReviewSignoff.lesson_id.in_(lesson_ids))
        .order_by(LessonReviewSignoff.lesson_id, LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc())
    ):
        approvals_by_lesson[record.lesson_id].setdefault(record.kind, record)
    result = {}
    for lesson_id in lesson_ids:
        segments = segments_by_lesson[lesson_id]
        points = points_by_lesson[lesson_id]
        key_material = [
            {"segmentId": str(segment.id), "body": segment.body} for segment in segments
        ] + [
            {"id": str(point.id), "segmentId": str(point.segment_id), "text": point.text,
             "source": point.source_text, "omitted": point.review_state == KeyPointReviewState.REMOVED}
            for point in points
        ]
        rewrites = [
            {"segmentId": str(segment.id), "kind": kind, "body": item["body"], "source": segment.body}
            for segment in segments for kind in ("simplified", "expanded")
            if isinstance(item := (segment.depth_variants or {}).get(kind), dict) and item.get("body")
        ]
        guided, _, _ = _guided_steps_material(segments)
        checks, _ = _checks_material(
            segments, lessons[lesson_id].assessment or [] if lesson_id in lessons else []
        )
        materials = {"key_points": key_material, "rewrites": rewrites,
                     "guided_steps": guided, "checks": checks}
        approvals = approvals_by_lesson[lesson_id]
        result[lesson_id] = bool(segments) and all(
            not material or (kind in approvals and _current_signoff(approvals[kind], material))
            for kind, material in materials.items()
        ) and "key_points" in approvals and _current_signoff(approvals["key_points"], key_material)
    return result


async def _review_result(session, lesson):
    from nevo.api.deferred_media import _view as media_view
    from nevo.api.deferred_media import media_summary, reviewable_media
    rows, segments, points, rewrites = await _review_material(session, lesson)
    guided_material, guided_views, pending_guided_count = _guided_steps_material(segments)
    checks_material, check_views = _checks_material(segments, lesson.assessment or [])
    calculation_material, calculation_views = _calculation_parts_material(segments)
    result = _review(lesson, rows)
    hashes = {
        "key_points": _hash(points),
        "rewrites": _hash(rewrites),
        "guided_steps": _hash(guided_material),
        "checks": _hash(checks_material),
        "calculation_parts": _hash(calculation_material),
    }
    approvals = {}
    media_rows = await session.execute(
        select(DeferredLessonMedia, LessonSegment)
        .join(LessonSegment, LessonSegment.id == DeferredLessonMedia.segment_id)
        .where(DeferredLessonMedia.lesson_id == lesson.id, reviewable_media())
        .order_by(LessonSegment.sequence_order, DeferredLessonMedia.kind)
    )
    result.media = LessonMediaResponse(
        lesson_id=lesson.id,
        summary=await media_summary(session, lesson.id),
        items=[media_view(job, segment) for job, segment in media_rows],
    )
    for record in await session.scalars(
        select(LessonReviewSignoff)
        .where(LessonReviewSignoff.lesson_id == lesson.id)
        .order_by(LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc())
    ):
        approvals.setdefault(
            record.kind,
            ReviewSignoffResponse(
                id=record.id,
                kind=record.kind,
                approved_by=record.approved_by,
                approved_by_name=record.approved_by_name,
                approved_at=record.approved_at,
                content_hash=record.content_hash,
                current=_current_signoff(record, {
                    "key_points": points, "rewrites": rewrites,
                    "guided_steps": guided_material, "checks": checks_material,
                    "calculation_parts": calculation_material,
                }[record.kind]),
            ),
        )
    return result.model_copy(
        update={
            "ready_to_assign": result.outstanding_count == 0
            and bool(approvals.get("key_points") and approvals["key_points"].current)
            and (not rewrites or bool(approvals.get("rewrites") and approvals["rewrites"].current))
            and (not guided_material or bool(approvals.get("guided_steps") and approvals["guided_steps"].current))
            and (not checks_material or bool(approvals.get("checks") and approvals["checks"].current)),
            "key_points_content_hash": hashes["key_points"],
            "rewrites_content_hash": hashes["rewrites"],
            "key_point_approval": approvals.get("key_points"),
            "rewrite_approval": approvals.get("rewrites"),
            "missing_key_point_segment_ids": [
                segment.id
                for segment in segments
                if not any(point.segment_id == segment.id for point, _ in rows)
            ],
            "rewrite_count": len(rewrites),
            "pending_rewrite_count": sum(
                not depth_approved((segment.depth_variants or {}).get(kind))
                for segment in segments
                for kind in ("simplified", "expanded")
                if isinstance((segment.depth_variants or {}).get(kind), dict)
                and (segment.depth_variants or {})[kind].get("body")
            ),
            "review_complete": bool(approvals.get("key_points") and approvals["key_points"].current)
            and (not rewrites or bool(approvals.get("rewrites") and approvals["rewrites"].current))
            and (
                not guided_material
                or bool(approvals.get("guided_steps") and approvals["guided_steps"].current)
            )
            and (not checks_material or bool(approvals.get("checks") and approvals["checks"].current)),
            "checks": [item.model_copy(update={"teacher_reviewed": item.markable and (item.teacher_reviewed or bool(
                approvals.get("checks") and approvals["checks"].current
            ))}) for item in check_views],
            "checks_content_hash": hashes["checks"],
            "checks_approval": approvals.get("checks"),
            "guided_steps": guided_views,
            "guided_steps_content_hash": hashes["guided_steps"],
            "guided_steps_approval": approvals.get("guided_steps"),
            "calculation_parts_approval": approvals.get("calculation_parts"),
            "calculation_parts_content_hash": hashes["calculation_parts"],
            "calculation_parts": calculation_views,
            "pending_guided_step_count": pending_guided_count,
        }
    )


async def _bulk_approve(session, lesson, actor, payload, kind):
    rows, segments, points, rewrites = await _review_material(session, lesson)
    if lesson.status not in {"completed", "completed_with_review"} or not segments:
        raise HTTPException(
            409,
            detail={
                "code": "lesson_not_ready_for_review",
                "message": "Wait for the lesson to finish processing before approving.",
            },
        )
    material = points if kind == "key_points" else rewrites
    digest = _hash(material)
    if digest != payload.expected_content_hash:
        raise HTTPException(
            409,
            detail={
                "code": "review_content_changed",
                "message": "The lesson changed. Read it again before approving.",
            },
        )
    if kind == "key_points" and any(
        not any(point.segment_id == segment.id for point, _ in rows) for segment in segments
    ):
        raise HTTPException(
            409,
            detail={
                "code": "key_point_decision_required",
                "message": "Add or omit each missing key point before approving.",
            },
        )
    if kind == "rewrites" and not rewrites:
        raise HTTPException(
            409,
            detail={
                "code": "no_rewrites_to_approve",
                "message": "This lesson has no rewrites to approve.",
            },
        )
    latest = await session.scalar(
        select(LessonReviewSignoff)
        .where(LessonReviewSignoff.lesson_id == lesson.id, LessonReviewSignoff.kind == kind)
        .order_by(LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    reuse = (
        latest is not None
        and latest.content_hash == digest
        and latest.approved_by == actor.id
        and latest.invalidated_at is None
    )
    if not reuse:
        session.add(
            LessonReviewSignoff(
                lesson_id=lesson.id,
                kind=kind,
                approved_by=actor.id,
                approved_by_name=" ".join(
                    part for part in (actor.first_name, actor.last_name) if part
                )
                or actor.email
                or str(actor.id),
                approved_at=now,
                content_hash=digest,
                content_snapshot=material,
            )
        )
    else:
        now = latest.approved_at
    reviewer = latest.approved_by if reuse else actor.id
    if kind == "key_points":
        for point, _ in rows:
            if point.review_state != KeyPointReviewState.REMOVED:
                point.review_state = (
                    KeyPointReviewState.AMENDED
                    if point.amended_text
                    else KeyPointReviewState.ACCEPTED
                )
                point.resolved_by, point.resolved_at = reviewer, now
    else:
        for segment in segments:
            variants = dict(segment.depth_variants or {})
            for key in ("simplified", "expanded"):
                if isinstance(variants.get(key), dict) and variants[key].get("body"):
                    variants[key] = {
                        **variants[key],
                        "reviewStatus": "approved",
                        "reviewedBy": str(reviewer),
                        "reviewedAt": now.isoformat(),
                    }
            segment.depth_variants = variants
    await session.commit()
    return await _review_result(session, lesson)


@router.post(
    "/lessons/{lesson_id}/key-points/approve-all",
    response_model=LessonReviewResponse,
    responses={409: {"description": "review_content_changed or key_point_decision_required"}},
)
async def approve_all_key_points(
    lesson_id: UUID,
    payload: BulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """One professional sign-off over the lesson's complete key-point set."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    return await _bulk_approve(session, lesson, actor, payload, "key_points")


@router.post(
    "/lessons/{lesson_id}/rewrites/approve-all",
    response_model=LessonReviewResponse,
    responses={409: {"description": "review_content_changed or no_rewrites_to_approve"}},
)
async def approve_all_rewrites(
    lesson_id: UUID,
    payload: BulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """One sign-off over all existing Simplify/Expand rewrites; no generation."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    return await _bulk_approve(session, lesson, actor, payload, "rewrites")


@router.post(
    "/lessons/{lesson_id}/checks/approve-all",
    response_model=LessonReviewResponse,
    responses={409: {"description": "review_content_changed or no_checks_to_approve"}},
)
async def approve_all_checks(
    lesson_id: UUID,
    payload: BulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """Sign off the questions and answer keys, separately from key points."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    if lesson.status not in {"completed", "completed_with_review"}:
        raise HTTPException(409, detail={"code": "lesson_not_ready_for_review"})
    current_review = await _review_result(session, lesson)
    if not current_review.key_point_approval or not current_review.key_point_approval.current:
        raise HTTPException(409, detail={"code": "key_points_approval_required"})
    segments = list(await session.scalars(
        select(LessonSegment).where(LessonSegment.lesson_id == lesson.id)
        .order_by(LessonSegment.sequence_order, LessonSegment.id).with_for_update()
    ))
    material, _ = _checks_material(segments, lesson.assessment or [])
    digest = _hash(material)
    if digest != payload.expected_content_hash:
        raise HTTPException(409, detail={"code": "review_content_changed"})
    if not material:
        raise HTTPException(409, detail={"code": "no_checks_to_approve"})
    if any(not item.get("questionPrompt") or item.get("questionAnswerKey") is None for item in material):
        raise HTTPException(409, detail={"code": "unmarkable_check"})
    reviewer_name = " ".join(part for part in (actor.first_name, actor.last_name) if part)
    session.add(LessonReviewSignoff(
        lesson_id=lesson.id, kind="checks", approved_by=actor.id,
        approved_by_name=reviewer_name or actor.email or str(actor.id),
        approved_at=datetime.now(UTC), content_hash=digest, content_snapshot=material,
    ))
    await session.commit()
    return await _review_result(session, lesson)


@router.post(
    "/lessons/{lesson_id}/guided-steps/approve-all",
    response_model=LessonReviewResponse,
    responses={409: {"description": "review_content_changed or no_guided_steps_to_approve"}},
)
async def approve_all_guided_steps(
    lesson_id: UUID,
    payload: GuidedStepsBulkReviewRequest,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> LessonReviewResponse:
    """Teacher sign-off over all generated, answer-bearing guided steps."""

    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segments = list(
        await session.scalars(
            select(LessonSegment)
            .where(LessonSegment.lesson_id == lesson.id)
            .order_by(LessonSegment.sequence_order, LessonSegment.id)
            .with_for_update()
        )
    )
    material, _, pending_count = _guided_steps_material(segments)
    digest = _hash(material)
    if digest != payload.expected_content_hash:
        raise HTTPException(
            409,
            detail={
                "code": "review_content_changed",
                "message": "The lesson changed. Read the guided steps again before approving.",
            },
        )
    if not material:
        raise HTTPException(
            409,
            detail={
                "code": "no_guided_steps_to_approve",
                "message": "This lesson has no generated guided steps awaiting review.",
            },
        )
    latest = await session.scalar(
        select(LessonReviewSignoff)
        .where(
            LessonReviewSignoff.lesson_id == lesson.id,
            LessonReviewSignoff.kind == "guided_steps",
        )
        .order_by(LessonReviewSignoff.approved_at.desc(), LessonReviewSignoff.id.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    if pending_count:
        reviewer_name = " ".join(
            part for part in (actor.first_name, actor.last_name) if part
        ) or actor.email or str(actor.id)
        session.add(
            LessonReviewSignoff(
                lesson_id=lesson.id,
                kind="guided_steps",
                approved_by=actor.id,
                approved_by_name=reviewer_name,
                approved_at=now,
                content_hash=digest,
                content_snapshot=material,
            )
        )
        for segment in segments:
            checkpoints = [dict(question) for question in segment.comprehension_checkpoints or []]
            changed = False
            for question in checkpoints:
                pending_steps = question.pop("pendingGuidedSteps", None)
                if pending_steps:
                    question["guidedSteps"] = pending_steps
                    question["guidedStepsReviewStatus"] = "approved"
                    changed = True
                elif question.get("guidedSteps") and question.get("guidedStepsReviewStatus") == "pending_review":
                    question["guidedStepsReviewStatus"] = "approved"
                    changed = True
            if changed:
                segment.comprehension_checkpoints = checkpoints
    elif latest is None or latest.content_hash != digest or latest.invalidated_at is not None:
        raise HTTPException(
            409,
            detail={
                "code": "guided_steps_already_reviewed",
                "message": "These guided steps were already reviewed; refresh the lesson review.",
            },
        )
    await session.commit()
    return await _review_result(session, lesson)


@router.put(
    "/lessons/{lesson_id}/segments/{segment_id}/key-point",
    response_model=LessonReviewResponse,
    responses={409: {"description": "key_point_already_exists"}},
)
async def resolve_missing_key_point(
    lesson_id: UUID,
    segment_id: UUID,
    payload: MissingKeyPointWrite,
    principal: PrincipalDependency,
    session: DatabaseSession,
):
    """Persist an authored point or an explicit omission where extraction found none."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segment = await session.get(LessonSegment, segment_id)
    if not segment or segment.lesson_id != lesson.id:
        raise HTTPException(404, detail="Segment not found")
    points = list(
        await session.scalars(select(LessonKeyPoint).where(LessonKeyPoint.segment_id == segment.id))
    )
    if any(point.extracted_text for point in points):
        raise HTTPException(
            409,
            detail={
                "code": "key_point_already_exists",
                "message": "Edit the existing key point instead.",
            },
        )
    point = (
        points[0]
        if points
        else LessonKeyPoint(
            lesson_id=lesson.id,
            segment_id=segment.id,
            position=0,
            extracted_text="",
            source_text=segment.body,
            confidence=KeyPointConfidence.LOW,
        )
    )
    if (
        not points
        or point.text != (payload.text or "")
        or (point.review_state == KeyPointReviewState.REMOVED) != (payload.action == "omit")
    ):
        await _invalidate_signoffs(session, lesson.id, "key_points")
    point.amended_text = payload.text if payload.action == "add" else None
    _resolve(
        point,
        state=KeyPointReviewState.AMENDED
        if payload.action == "add"
        else KeyPointReviewState.REMOVED,
        actor=actor,
    )
    session.add(point)
    await _write_through(session, point)
    await session.commit()
    return await _review_result(session, lesson)


@router.patch(
    "/lessons/{lesson_id}/segments/{segment_id}/rewrites/{variant}",
    response_model=LessonReviewResponse,
)
async def edit_rewrite(
    lesson_id: UUID,
    segment_id: UUID,
    variant: Literal["simplified", "expanded"],
    payload: RewriteEdit,
    principal: PrincipalDependency,
    session: DatabaseSession,
    gateway: AiGatewayDependency,
):
    """Save wording as pending; only the lesson-wide act approves it."""
    lesson, actor = await _lesson_for_review(session, principal, lesson_id)
    segment = await session.get(LessonSegment, segment_id)
    if not segment or segment.lesson_id != lesson.id:
        raise HTTPException(404, detail="Segment not found")
    variants = dict(segment.depth_variants or {})
    original = variants.get(variant)
    if not isinstance(original, dict) or not original.get("body"):
        raise HTTPException(404, detail="Rewrite not found")
    if original["body"] != payload.body:
        try:
            await gateway.check_content(
                payload.body, requester_user_id=actor.id, phase="lesson_rewrite"
            )
        except AiGatewayError as error:
            raise public_ai_error(error, audience="teacher") from error
        await _invalidate_signoffs(session, lesson.id, "rewrites")
        changed = {
            **original,
            "originalBody": original.get("originalBody", original["body"]),
            "body": payload.body,
            "safetyPolicyVersion": POLICY_VERSION,
            "reviewStatus": "pending",
            "reviewedBy": None,
            "reviewedAt": None,
            "reviewedByName": None,
            "editedBy": str(actor.id),
            "editedAt": datetime.now(UTC).isoformat(),
        }
        variants[variant] = changed
        segment.depth_variants = variants
        await session.commit()
    return await _review_result(session, lesson)


async def outstanding_key_points(
    session: AsyncSession,
    lesson_ids: list[UUID],
) -> dict[UUID, int]:
    """How many points each lesson is still waiting on.

    Shared with the assignment gate, so "ready" means the same thing to the
    screen that counts down and to the endpoint that refuses.
    """

    if not lesson_ids:
        return {}
    rows = await session.execute(
        select(LessonKeyPoint.lesson_id, func.count(LessonKeyPoint.id))
        .where(
            LessonKeyPoint.lesson_id.in_(lesson_ids),
            LessonKeyPoint.review_state == KeyPointReviewState.UNSURE,
        )
        .group_by(LessonKeyPoint.lesson_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]
