from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
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

    @classmethod
    def from_schedule(cls, schedule: ConceptSchedule) -> "ConceptScheduleResponse":
        return cls(
            student_id=schedule.student_id,
            concept_id=schedule.concept_id,
            stability=round(schedule.stability, 6),
            difficulty=round(schedule.difficulty, 6),
            retrievability=round(schedule.retrievability, 6),
            last_review=schedule.last_review,
            review_count=schedule.review_count,
            next_review_due=schedule.next_review_due,
        )


class RecordReviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    recall_successful: bool = Field(alias="recallSuccessful")
    reviewed_at: datetime | None = Field(default=None, alias="reviewedAt")


class RecordReviewResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schedule: ConceptScheduleResponse
    recall_successful: bool = Field(alias="recallSuccessful")

    @classmethod
    def from_result(cls, result: ReviewResult) -> "RecordReviewResponse":
        return cls(
            schedule=ConceptScheduleResponse.from_schedule(result.schedule),
            recall_successful=result.recall_successful,
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
) -> list[ConceptScheduleResponse]:
    if principal.role == "student" and principal.user_id != student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Students can view only their own review schedule.",
            },
        )
    schedules = await service.due_reviews(student_id=student_id)
    return [ConceptScheduleResponse.from_schedule(schedule) for schedule in schedules]


@router.post("/record-review", response_model=RecordReviewResponse)
async def record_review(
    payload: RecordReviewRequest,
    principal: PrincipalDependency,
    service: SchedulerDependency,
) -> RecordReviewResponse:
    if principal.role == "student" and principal.user_id != payload.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Students can update only their own review schedule.",
            },
        )
    reviewed_at = payload.reviewed_at
    if reviewed_at is not None and reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=UTC)
    result = await service.record_review(
        student_id=payload.student_id,
        concept_id=payload.concept_id,
        recall_successful=payload.recall_successful,
        reviewed_at=reviewed_at,
    )
    return RecordReviewResponse.from_result(result)


@router.post("/refresh-due-dates", response_model=RefreshSchedulesResponse)
async def refresh_due_dates(
    principal: PrincipalDependency,
    service: SchedulerDependency,
) -> RefreshSchedulesResponse:
    if principal.role not in {"admin", "school_admin", "teacher"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "scheduler_refresh_forbidden",
                "message": "Only staff can refresh review schedules.",
            },
        )
    schedules = await service.refresh_all_due_dates()
    return RefreshSchedulesResponse(refreshed_count=len(schedules))
