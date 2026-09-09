"""What a signed-in parent can read: their own children, and how they learn."""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.consent.entities import ParentChildView
from nevo.domain.accounts.vocabulary import UserStatus
from nevo.domain.parents.vocabulary import GrowthDimension, GrowthTrend
from nevo.parents.entities import GrowthNarrative, GrowthStatement
from nevo.parents.errors import ChildNotLinkedError
from nevo.parents.service import ParentInsightService

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
                GrowthStatementResponse.from_statement(item)
                for item in narrative.statements
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


@router.get("/parents/me/children", response_model=list[ParentChildResponse])
async def my_children(
    parent_id: ParentDependency,
    service: ParentInsightDependency,
) -> list[ParentChildResponse]:
    """The learners this parent is linked to.

    The parent equivalent of students/me: without it a signed-in parent has
    no way to find their own child, since the admin read runs the other way.
    """
    return [
        ParentChildResponse.from_view(view) for view in await service.children(parent_id)
    ]


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
