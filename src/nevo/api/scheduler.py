from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import require_school_actor, require_student_access
from nevo.scheduler.entities import ConceptSchedule, ReviewResult
from nevo.scheduler.service import FsrsSchedulerService

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class ConceptScheduleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    stability: float
    difficulty: float
    retrievability: float
    last_review: datetime = Field(alias="lastReview")
    review_count: int = Field(alias="reviewCount")
    next_review_due: datetime = Field(alias="nextReviewDue")
    lesson_id: UUID | None = Field(default=None, alias="lessonId")

    @classmethod
    def from_schedule(
        cls, schedule: ConceptSchedule, *, lesson_id: UUID | None = None
    ) -> "ConceptScheduleResponse":
        return cls(
            student_id=schedule.student_id,
            concept_id=schedule.concept_id,
            stability=round(schedule.stability, 6),
            difficulty=round(schedule.difficulty, 6),
            retrievability=round(schedule.retrievability, 6),
            last_review=schedule.last_review,
            review_count=schedule.review_count,
            next_review_due=schedule.next_review_due,
            lesson_id=lesson_id if lesson_id is not None else schedule.lesson_id,
        )


class ReviewOutcome(StrEnum):
    """How a review actually went.

    ``recallSuccessful`` alone made the client decide what "all right first
    time" meant, which is the client deciding a measure. These four are what
    the screen can observe; whether each counts as recall is decided here.
    """

    #: Right, unaided, first attempt. The only one that means untroubled
    #: recall, and the only one that lengthens the interval.
    FIRST_TIME = "first_time"
    #: Right, but a hint was used getting there.
    AFTER_HINT = "after_hint"
    #: Right on a second attempt.
    SECOND_ATTEMPT = "second_attempt"
    #: Not recalled.
    NOT_RECALLED = "not_recalled"


#: Which outcomes count as the concept having been recalled. A hint or a
#: second attempt is a pass for the lesson and not for the scheduler: a child
#: who needed help remembering needs to see it again sooner, not later.
RECALLED = frozenset({ReviewOutcome.FIRST_TIME})


class RecordReviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    #: Preferred. Send this and leave recallSuccessful out.
    outcome: ReviewOutcome | None = None
    #: The older shape, still accepted so nothing in flight breaks. Ignored
    #: when ``outcome`` is sent.
    recall_successful: bool | None = Field(default=None, alias="recallSuccessful")
    reviewed_at: datetime | None = Field(default=None, alias="reviewedAt")

    @model_validator(mode="after")
    def one_of_the_two(self) -> "RecordReviewRequest":
        if self.outcome is None and self.recall_successful is None:
            raise ValueError("Send outcome, or recallSuccessful.")
        return self

    @property
    def recalled(self) -> bool:
        """Whether this counts as recall, decided here and not on the device."""

        if self.outcome is not None:
            return self.outcome in RECALLED
        return bool(self.recall_successful)


class RecordReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schedule: ConceptScheduleResponse
    recall_successful: bool = Field(alias="recallSuccessful")
    #: Echoed back so a client can see which outcome the server scored, rather
    #: than inferring it from the bool.
    outcome: ReviewOutcome | None = None

    @classmethod
    def from_result(
        cls, result: ReviewResult, outcome: ReviewOutcome | None = None
    ) -> "RecordReviewResponse":
        return cls(
            schedule=ConceptScheduleResponse.from_schedule(result.schedule),
            recall_successful=result.recall_successful,
            outcome=outcome,
        )


class RefreshSchedulesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    refreshed_count: int = Field(alias="refreshedCount")


def get_scheduler_service(request: Request) -> FsrsSchedulerService:
    service = getattr(request.app.state, "scheduler_service", None)
    if not isinstance(service, FsrsSchedulerService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Review scheduling is temporarily unavailable.",
            },
        )
    return service


SchedulerDependency = Annotated[FsrsSchedulerService, Depends(get_scheduler_service)]


@router.get(
    "/due-reviews/{student_id}",
    response_model=list[ConceptScheduleResponse],
)
async def due_reviews(
    student_id: UUID,
    principal: PrincipalDependency,
    service: SchedulerDependency,
    session: DatabaseSession,
) -> list[ConceptScheduleResponse]:
    await require_student_access(session, principal, student_id)
    schedules = await service.due_reviews(student_id=student_id)
    return [ConceptScheduleResponse.from_schedule(schedule) for schedule in schedules]


@router.post("/record-review", response_model=RecordReviewResponse)
async def record_review(
    payload: RecordReviewRequest,
    principal: PrincipalDependency,
    service: SchedulerDependency,
    session: DatabaseSession,
) -> RecordReviewResponse:
    await require_student_access(session, principal, payload.student_id)
    reviewed_at = payload.reviewed_at
    if reviewed_at is not None and reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=UTC)
    result = await service.record_review(
        student_id=payload.student_id,
        concept_id=payload.concept_id,
        # Scored from the outcome here rather than taken as a bool from the
        # device, so "all right first time" means one thing everywhere.
        recall_successful=payload.recalled,
        reviewed_at=reviewed_at,
    )
    return RecordReviewResponse.from_result(result, payload.outcome)


@router.post("/refresh-due-dates", response_model=RefreshSchedulesResponse)
async def refresh_due_dates(
    principal: PrincipalDependency,
    service: SchedulerDependency,
    session: DatabaseSession,
) -> RefreshSchedulesResponse:
    await require_school_actor(session, principal, roles={"teacher", "senco_admin", "other_admin"})
    schedules = await service.refresh_all_due_dates()
    return RefreshSchedulesResponse(refreshed_count=len(schedules))
