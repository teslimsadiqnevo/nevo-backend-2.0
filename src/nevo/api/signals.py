from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nevo.api.auth import PrincipalDependency
from nevo.api.privacy import is_private_interaction_key
from nevo.domain.signal_events.vocabulary import (
    LessonCompletionStatus,
    SignalEventType,
)
from nevo.learner_profiles.post_lesson_worker import PostLessonProcessingWorker
from nevo.signal_events.entities import (
    LessonSessionSnapshot,
    SignalEventDraft,
    SignalIngestionBatch,
    SignalIngestionReceipt,
)
from nevo.signal_events.errors import SignalIngestionError
from nevo.signal_events.service import MAX_SIGNAL_BATCH_SIZE, SignalIngestionService

router = APIRouter(prefix="/api/signals", tags=["signals"])

STUDENT_ASK_NEVO_CATEGORIES = {
    "comprehension",
    "vocabulary",
    "navigation",
    "general",
}
TEACHER_ASK_NEVO_CATEGORIES = {
    "student_insight",
    "class_pattern",
    "lesson_recommendation",
    "communication_help",
    "general",
}
FORBIDDEN_ASK_NEVO_TEXT_KEYS = {
    "question",
    "questionText",
    "fullQuestion",
    "prompt",
    "message",
    "text",
}
class LessonSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID = Field(alias="sessionId")
    lesson_id: UUID | None = Field(default=None, alias="lessonId")
    session_type: Literal["lesson", "onboarding", "profiling", "sso"] = Field(
        default="lesson", alias="sessionType"
    )
    started_at: datetime = Field(alias="startedAt")
    ended_at: datetime | None = Field(default=None, alias="endedAt")
    completion_status: LessonCompletionStatus = Field(
        default=LessonCompletionStatus.IN_PROGRESS,
        alias="completionStatus",
    )
    exit_position: str | None = Field(
        default=None,
        alias="exitPosition",
        max_length=120,
    )
    break_count: int = Field(default=0, alias="breakCount", ge=0)
    proactive_adjustments_count: int = Field(
        default=0,
        alias="proactiveAdjustmentsCount",
        ge=0,
    )


class SignalEventRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    session_id: UUID = Field(alias="sessionId")
    event_type: SignalEventType = Field(alias="eventType")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = Field(default_factory=dict, alias="eventData")

    @field_validator("event_data")
    @classmethod
    def bound_event_data(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 64:
            raise ValueError("Signal event data cannot contain more than 64 keys.")
        leaked_keys = {key for key in value if is_private_interaction_key(key)}
        if leaked_keys:
            joined = ", ".join(sorted(leaked_keys))
            raise ValueError(f"Ephemeral interaction signals cannot leave the device: {joined}.")
        return value

    @model_validator(mode="after")
    def merge_extra_event_fields(self) -> "SignalEventRequest":
        if self.model_extra:
            self.event_data = {**self.model_extra, **self.event_data}
        self._validate_ask_nevo_signal_payload()
        return self

    def _validate_ask_nevo_signal_payload(self) -> None:
        if self.event_type not in {
            SignalEventType.ASK_NEVO_QUESTION_STUDENT,
            SignalEventType.ASK_NEVO_QUESTION_TEACHER,
            SignalEventType.ASK_NEVO_CANNOT_HELP,
            SignalEventType.ASK_NEVO_REDIRECT_USED,
        }:
            return
        leaked_keys = FORBIDDEN_ASK_NEVO_TEXT_KEYS.intersection(self.event_data)
        if leaked_keys:
            joined = ", ".join(sorted(leaked_keys))
            raise ValueError(f"Ask Nevo signal cannot include full text fields: {joined}.")
        if self.event_type is SignalEventType.ASK_NEVO_QUESTION_STUDENT:
            _require_keys(
                self.event_data,
                {
                    "studentId",
                    "currentPage",
                    "lessonId",
                    "segmentId",
                    "questionCategory",
                },
            )
            _require_category(
                self.event_data,
                allowed=STUDENT_ASK_NEVO_CATEGORIES,
            )
        elif self.event_type is SignalEventType.ASK_NEVO_QUESTION_TEACHER:
            _require_keys(
                self.event_data,
                {
                    "teacherId",
                    "currentPage",
                    "questionCategory",
                },
            )
            _require_category(
                self.event_data,
                allowed=TEACHER_ASK_NEVO_CATEGORIES,
            )
        elif self.event_type is SignalEventType.ASK_NEVO_CANNOT_HELP:
            _require_keys(self.event_data, {"role", "currentPage"})
            if self.event_data.get("role") not in {"student", "teacher"}:
                raise ValueError("Ask Nevo cannot-help role must be student or teacher.")
        elif self.event_type is SignalEventType.ASK_NEVO_REDIRECT_USED:
            _require_keys(self.event_data, {"role", "currentPage", "redirectTarget"})
            if self.event_data.get("role") not in {"student", "teacher"}:
                raise ValueError("Ask Nevo redirect role must be student or teacher.")


def _require_keys(payload: dict[str, Any], keys: set[str]) -> None:
    missing = sorted(key for key in keys if payload.get(key) in {None, ""})
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Ask Nevo signal missing required field(s): {joined}.")


def _require_category(payload: dict[str, Any], *, allowed: set[str]) -> None:
    category = payload.get("questionCategory")
    if category not in allowed:
        joined = ", ".join(sorted(allowed))
        raise ValueError(f"Ask Nevo questionCategory must be one of: {joined}.")


class SignalBatchRequest(BaseModel):
    session: LessonSessionRequest
    events: list[SignalEventRequest] = Field(
        min_length=1,
        max_length=MAX_SIGNAL_BATCH_SIZE,
    )


class SignalBatchResponse(BaseModel):
    session_id: UUID
    accepted_events: int

    @classmethod
    def from_receipt(cls, receipt: SignalIngestionReceipt) -> "SignalBatchResponse":
        return cls(
            session_id=receipt.session_id,
            accepted_events=receipt.accepted_events,
        )


def get_signal_ingestion_service(request: Request) -> SignalIngestionService:
    service = getattr(request.app.state, "signal_ingestion_service", None)
    if not isinstance(service, SignalIngestionService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Signal ingestion is temporarily unavailable.",
            },
        )
    return service


SignalIngestionDependency = Annotated[
    SignalIngestionService,
    Depends(get_signal_ingestion_service),
]


@router.post("/", response_model=SignalBatchResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_signal_batch(
    payload: SignalBatchRequest,
    principal: PrincipalDependency,
    service: SignalIngestionDependency,
    request: Request,
) -> SignalBatchResponse:
    if principal.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "student_required", "message": "Student account required."},
        )
    try:
        receipt = await service.ingest(
            SignalIngestionBatch(
                session=LessonSessionSnapshot(
                    id=payload.session.session_id,
                    student_id=principal.user_id,
                    lesson_id=payload.session.lesson_id,
                    session_type=payload.session.session_type,
                    started_at=payload.session.started_at,
                    ended_at=payload.session.ended_at,
                    completion_status=payload.session.completion_status,
                    exit_position=payload.session.exit_position,
                    break_count=payload.session.break_count,
                    proactive_adjustments_count=(payload.session.proactive_adjustments_count),
                ),
                events=tuple(
                    SignalEventDraft(
                        student_id=principal.user_id,
                        session_id=event.session_id,
                        event_type=event.event_type,
                        event_data=event.event_data,
                        timestamp=event.timestamp,
                    )
                    for event in payload.events
                ),
            )
        )
    except SignalIngestionError as error:
        raise public_signal_error(error) from error
    if (
        payload.session.lesson_id is not None
        and payload.session.completion_status is LessonCompletionStatus.COMPLETED
    ):
        worker = getattr(request.app.state, "post_lesson_worker", None)
        if isinstance(worker, PostLessonProcessingWorker):
            await worker.enqueue(
                session_id=payload.session.session_id,
                student_id=principal.user_id,
                completed_at=payload.session.ended_at,
            )
    return SignalBatchResponse.from_receipt(receipt)


def public_signal_error(error: SignalIngestionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )
