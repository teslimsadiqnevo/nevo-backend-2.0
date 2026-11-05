"""What a signed-in parent can read: their own children, and how they learn."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.response_models import CamelResponse
from nevo.db.models.frontend_support import Concept
from nevo.db.models.mastery import StudentConceptLevelMastery, StudentConceptScheduling
from nevo.db.models.out_of_school import OutOfSchoolLearning
from nevo.consent.entities import ParentChildView
from nevo.domain.accounts.vocabulary import UserStatus
from nevo.domain.parents.vocabulary import GrowthDimension, GrowthTrend
from nevo.parents.entities import GrowthNarrative, GrowthStatement
from nevo.parents.errors import ChildNotLinkedError
from nevo.parents.service import ParentInsightService
from nevo.parents.subject_progress import SubjectState, WindowState
from nevo.parents.subject_reader import child_subject_progress as child_progress

router = APIRouter(prefix="/api/v1", tags=["parent"])


class ParentChildResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    first_name: str | None = Field(alias="firstName")
    last_name: str | None = Field(alias="lastName")
    status: UserStatus
    school_id: UUID = Field(alias="schoolId")
    school_name: str = Field(alias="schoolName")

    @classmethod
    def from_view(cls, view: ParentChildView) -> "ParentChildResponse":
        return cls(
            studentId=view.student_id,
            firstName=view.first_name,
            lastName=view.last_name,
            status=view.status,
            schoolId=view.school_id,
            schoolName=view.school_name,
        )


class GrowthStatementResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dimension: GrowthDimension
    trend: GrowthTrend
    statement: str

    @classmethod
    def from_statement(cls, item: GrowthStatement) -> "GrowthStatementResponse":
        return cls(dimension=item.dimension, trend=item.trend, statement=item.statement)


class GrowthNarrativeResponse(BaseModel):
    """Four plain-language statements about one child, and nothing numeric.

    The window dates are here so the screen can say what it compared. There
    are no term dates in the roster, so a page claiming "last term" would be
    claiming something the backend cannot support.
    """

    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    student_first_name: str = Field(alias="studentFirstName")
    headline: str
    summary: str
    statements: list[GrowthStatementResponse]
    period_start: date = Field(alias="periodStart")
    period_end: date = Field(alias="periodEnd")
    comparison_start: date = Field(alias="comparisonStart")
    comparison_end: date = Field(alias="comparisonEnd")
    generated_at: datetime = Field(alias="generatedAt")
    source: Literal["live_learning_data"] = "live_learning_data"

    @classmethod
    def from_narrative(cls, narrative: GrowthNarrative) -> "GrowthNarrativeResponse":
        return cls(
            studentId=narrative.student_id,
            studentFirstName=narrative.student_first_name,
            headline=narrative.headline,
            summary=narrative.summary,
            statements=[
                GrowthStatementResponse.from_statement(item) for item in narrative.statements
            ],
            periodStart=narrative.period_start,
            periodEnd=narrative.period_end,
            comparisonStart=narrative.comparison_start,
            comparisonEnd=narrative.comparison_end,
            generatedAt=narrative.generated_at,
        )


def get_parent_insight_service(request: Request) -> ParentInsightService:
    service = getattr(request.app.state, "parent_insight_service", None)
    if not isinstance(service, ParentInsightService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Parent services are temporarily unavailable.",
            },
        )
    return service


ParentInsightDependency = Annotated[
    ParentInsightService,
    Depends(get_parent_insight_service),
]


def require_parent(principal: PrincipalDependency) -> UUID:
    if principal.role != "parent_guardian":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "parent_only",
                "message": "Only a parent or guardian can read this.",
            },
        )
    return principal.user_id


ParentDependency = Annotated[UUID, Depends(require_parent)]


class StrengthenedConcept(CamelResponse):
    concept_id: UUID
    concept_name: str
    recorded_at: datetime
    source: Literal["server_marked_practice"] = "server_marked_practice"


class ScheduledConceptReturn(CamelResponse):
    concept_id: UUID
    concept_name: str
    due_at: datetime


class ReportedOutsideWork(CamelResponse):
    concept_id: UUID
    concept_name: str
    activity_kind: Literal["reading", "practice", "discussion", "paper_work"]
    recorded_at: datetime
    source: Literal["learner_report"] = "learner_report"


class ParentLearningEvidence(CamelResponse):
    student_id: UUID
    strengthened_concepts: list[StrengthenedConcept]
    scheduled_returns: list[ScheduledConceptReturn]
    out_of_school_learning: list[ReportedOutsideWork]


@router.get("/parents/me/children/{student_id}/learning-evidence", response_model=ParentLearningEvidence)
async def parent_learning_evidence(
    student_id: UUID,
    parent_id: ParentDependency,
    session: DatabaseSession,
    service: ParentInsightDependency,
) -> ParentLearningEvidence:
    await service.require_linked_child(parent_id=parent_id, student_id=student_id)
    strengthened = (await session.execute(
        select(StudentConceptLevelMastery, Concept)
        .join(Concept, Concept.id == StudentConceptLevelMastery.concept_id)
        .where(StudentConceptLevelMastery.student_id == student_id,
               StudentConceptLevelMastery.strengthened_at.is_not(None))
        .order_by(StudentConceptLevelMastery.strengthened_at.desc()).limit(100)
    )).all()
    due = (await session.execute(
        select(StudentConceptScheduling, Concept)
        .join(Concept, Concept.id == StudentConceptScheduling.concept_id)
        .where(StudentConceptScheduling.student_id == student_id)
        .order_by(StudentConceptScheduling.next_review_due).limit(100)
    )).all()
    outside = (await session.execute(
        select(OutOfSchoolLearning, Concept)
        .join(Concept, Concept.id == OutOfSchoolLearning.concept_id)
        .where(OutOfSchoolLearning.student_id == student_id)
        .order_by(OutOfSchoolLearning.created_at.desc()).limit(100)
    )).all()
    by_concept = {}
    for row, concept in strengthened:
        by_concept.setdefault(concept.id, StrengthenedConcept(
            concept_id=concept.id, concept_name=concept.name,
            recorded_at=row.strengthened_at,
        ))
    return ParentLearningEvidence(
        student_id=student_id,
        strengthened_concepts=list(by_concept.values()),
        scheduled_returns=[ScheduledConceptReturn(
            concept_id=concept.id, concept_name=concept.name,
            due_at=row.next_review_due,
        ) for row, concept in due],
        out_of_school_learning=[ReportedOutsideWork(
            concept_id=concept.id, concept_name=concept.name,
            activity_kind=row.activity_kind, recorded_at=row.created_at,
        ) for row, concept in outside],
    )


@router.get("/parents/me/children", response_model=list[ParentChildResponse])
async def my_children(
    parent_id: ParentDependency,
    service: ParentInsightDependency,
) -> list[ParentChildResponse]:
    """The learners this parent is linked to.

    The parent equivalent of students/me: without it a signed-in parent has
    no way to find their own child, since the admin read runs the other way.
    """
    return [ParentChildResponse.from_view(view) for view in await service.children(parent_id)]


@router.get(
    "/parents/me/children/{student_id}/growth",
    response_model=GrowthNarrativeResponse,
)
async def child_growth(
    student_id: UUID,
    parent_id: ParentDependency,
    service: ParentInsightDependency,
) -> GrowthNarrativeResponse:
    try:
        narrative = await service.growth(parent_id=parent_id, student_id=student_id)
    except ChildNotLinkedError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code, "message": error.public_message},
        ) from error
    return GrowthNarrativeResponse.from_narrative(narrative)


class SubjectProgressResponse(CamelResponse):
    """One subject's week, for one child.

    Counts and concept names. There is deliberately no field for a score, an
    index, a percentile or a rating, and none for any figure about another
    child - so this shape cannot carry one even by accident. SCRUM-163's rule
    that no per-student transformation endpoint may exist is untouched: this is
    comprehension and mastery, which are per child by construction and were
    never struck.
    """

    subject_id: UUID
    subject_name: str
    state: SubjectState
    covered: list[str]
    mastered_this_window: list[str]
    still_working_on: list[str]
    #: What this child had already mastered when the week opened. Their own
    #: starting point, and the only thing this week's movement is measured
    #: against.
    mastered_before_window: int
    mastered_so_far: int
    last_lesson_at: datetime | None


class ProgressWindowResponse(CamelResponse):
    starts_on: date
    ends_on: date
    #: in_term, in_break or terms_not_set. The front end draws three different
    #: things for an empty week, and which one is decided here rather than
    #: reimplemented per surface.
    state: WindowState
    in_progress: bool
    kind: Literal["week", "since_setup"]


class ChildSubjectProgressResponse(CamelResponse):
    student_id: UUID
    window: ProgressWindowResponse
    subjects: list[SubjectProgressResponse]


@router.get(
    "/parents/me/children/{student_id}/subject-progress",
    response_model=ChildSubjectProgressResponse,
    responses={404: {"description": "child_not_linked when the learner is not this parent's"}},
)
async def child_subject_progress(
    student_id: UUID,
    parent_id: ParentDependency,
    session: DatabaseSession,
    service: ParentInsightDependency,
    week_of: Annotated[date | None, Query(alias="weekOf")] = None,
) -> ChildSubjectProgressResponse:
    """What this child covered and mastered in the reporting window.

    ``weekOf`` asks for a different week; any date in it will do. The default
    is the week in progress rather than the last complete one, because a parent
    opening this on Wednesday wants to know about Wednesday.
    Without term dates, the default is since school setup; explicit weekOf
    still selects a historical week. window.kind states which was selected.

    A parent reads only their own children, and the link is checked before any
    progress is read rather than after.
    """

    await service.require_linked_child(parent_id=parent_id, student_id=student_id)
    progress = await child_progress(
        session,
        student_id=student_id,
        now=datetime.now(UTC),
        week_of=week_of,
    )
    return ChildSubjectProgressResponse(
        student_id=progress.student_id,
        window=ProgressWindowResponse(
            starts_on=progress.window.starts_on,
            ends_on=progress.window.ends_on,
            state=progress.window.state,
            in_progress=progress.window.in_progress,
            kind=progress.window.kind,
        ),
        subjects=[
            SubjectProgressResponse(
                subject_id=row.subject_id,
                subject_name=row.subject_name,
                state=row.state,
                covered=list(row.covered),
                mastered_this_window=list(row.mastered_this_window),
                still_working_on=list(row.still_working_on),
                mastered_before_window=row.mastered_before_window,
                mastered_so_far=row.mastered_so_far,
                last_lesson_at=row.last_lesson_at,
            )
            for row in progress.subjects
        ],
    )
