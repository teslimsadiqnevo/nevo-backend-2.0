from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.api.product_common import (
    require_class_access,
    require_school_actor,
    require_student_access,
)
from nevo.db.models.product import LessonQuestionAttempt
from nevo.db.models.mastery import StudentConceptLevelMastery
from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.mastery.entities import (
    ConceptMasteryAggregate,
    MasteryState,
    MasteryUpdate,
    MasteryUpdateResult,
)
from nevo.mastery.service import MasteryService

router = APIRouter(prefix="/api/mastery", tags=["mastery"])


class ConceptLevelMasteryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    concept_id: UUID = Field(alias="conceptId")
    level: Literal["knowledge", "application", "analysis"]
    probability: float
    practice_count: int = Field(alias="practiceCount")
    independent_pass_count: int = Field(alias="independentPassCount")
    supported_pass_count: int = Field(alias="supportedPassCount")
    last_updated: datetime = Field(alias="lastUpdated")


@router.get("/student/{student_id}/levels", response_model=list[ConceptLevelMasteryResponse])
async def student_level_mastery(
    student_id: UUID,
    principal: PrincipalDependency,
    session: DatabaseSession,
) -> list[ConceptLevelMasteryResponse]:
    if principal.role not in {"teacher", "senco_admin", "other_admin"}:
        raise HTTPException(403, detail={"code": "staff_role_required"})
    await require_student_access(session, principal, student_id)
    rows = list(await session.scalars(
        select(StudentConceptLevelMastery)
        .where(StudentConceptLevelMastery.student_id == student_id)
        .order_by(StudentConceptLevelMastery.concept_id, StudentConceptLevelMastery.mastery_level)
    ))
    return [ConceptLevelMasteryResponse(
        concept_id=row.concept_id,
        level=row.mastery_level,
        probability=row.mastery_probability,
        practice_count=row.practice_count,
        independent_pass_count=row.independent_pass_count,
        supported_pass_count=row.supported_pass_count,
        last_updated=row.last_updated,
    ) for row in rows]


class MasteryUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    concept_name: str | None = Field(default=None, alias="conceptName")
    response_correct: bool = Field(alias="responseCorrect")
    item_text_density: float = Field(alias="itemTextDensity", ge=0, le=1)
    related_concept_ids: list[UUID] = Field(
        default_factory=list,
        alias="relatedConceptIds",
        max_length=50,
    )
    answer_attempt_id: UUID | None = Field(
        default=None,
        alias="answerAttemptId",
        description=(
            "A saved, server-marked attempt. Student writes require this; "
            "attempts already update mastery transactionally."
        ),
    )


class MasteryStateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    concept_name: str | None = Field(default=None, alias="conceptName")
    mastery_probability_concept: float | None = Field(alias="masteryProbabilityConcept")
    mastery_probability_reading: float | None = Field(alias="masteryProbabilityReading")
    attention_weights: dict[str, float] = Field(alias="attentionWeights")
    practice_count: int = Field(alias="practiceCount")
    last_response_correct: bool | None = Field(alias="lastResponseCorrect")
    last_failure_attribution: FailureAttribution = Field(alias="lastFailureAttribution")
    seeding_source: str = Field(alias="seedingSource")

    @classmethod
    def from_state(cls, state: MasteryState) -> "MasteryStateResponse":
        return cls(
            student_id=state.student_id,
            concept_id=state.concept_id,
            concept_name=state.concept_name,
            mastery_probability_concept=round(
                state.mastery_probability_concept,
                6,
            ),
            mastery_probability_reading=round(
                state.mastery_probability_reading,
                6,
            ),
            attention_weights={
                key: round(value, 6) for key, value in state.attention_weights.items()
            },
            practice_count=state.practice_count,
            last_response_correct=state.last_response_correct,
            last_failure_attribution=state.last_failure_attribution,
            seeding_source=state.seeding_source,
        )

    def for_student(self):
        return self.model_copy(
            update={
                "mastery_probability_concept": None,
                "mastery_probability_reading": None,
                "attention_weights": {},
                "last_response_correct": None,
                "last_failure_attribution": FailureAttribution.NONE,
                "seeding_source": "server_marked",
            }
        )


class MasteryUpdateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mastery: MasteryStateResponse
    attention_transfer: float = Field(alias="attentionTransfer")
    recommended_modality_shift: bool = Field(alias="recommendedModalityShift")

    @classmethod
    def from_result(cls, result: MasteryUpdateResult) -> "MasteryUpdateResponse":
        return cls(
            mastery=MasteryStateResponse.from_state(result.state),
            attention_transfer=result.attention_transfer,
            recommended_modality_shift=result.recommended_modality_shift,
        )


class ConceptMasteryAggregateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    concept_id: UUID = Field(alias="conceptId")
    concept_name: str | None = Field(default=None, alias="conceptName")
    student_count: int = Field(alias="studentCount")
    mastery_probability_concept: float = Field(alias="masteryProbabilityConcept")
    mastery_probability_reading: float = Field(alias="masteryProbabilityReading")

    @classmethod
    def from_aggregate(
        cls,
        aggregate: ConceptMasteryAggregate,
    ) -> "ConceptMasteryAggregateResponse":
        return cls(
            concept_id=aggregate.concept_id,
            concept_name=aggregate.concept_name,
            student_count=aggregate.student_count,
            mastery_probability_concept=aggregate.mastery_probability_concept,
            mastery_probability_reading=aggregate.mastery_probability_reading,
        )


def get_mastery_service(request: Request) -> MasteryService:
    service = getattr(request.app.state, "mastery_service", None)
    if not isinstance(service, MasteryService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Mastery is temporarily unavailable.",
            },
        )
    return service


MasteryDependency = Annotated[MasteryService, Depends(get_mastery_service)]


@router.post("/update", response_model=MasteryUpdateResponse)
async def update_mastery(
    payload: MasteryUpdateRequest,
    principal: PrincipalDependency,
    service: MasteryDependency,
    session: DatabaseSession,
) -> MasteryUpdateResponse:
    await require_student_access(session, principal, payload.student_id)
    if principal.role == "student":
        if payload.answer_attempt_id is None:
            raise HTTPException(
                422,
                detail={
                    "code": "server_marked_attempt_required",
                    "message": "Save the answer attempt first and send its id.",
                },
            )
        attempt = await session.get(LessonQuestionAttempt, payload.answer_attempt_id)
        if (
            attempt is None
            or attempt.student_id != principal.user_id
            or str(attempt.question_snapshot.get("conceptId")) != str(payload.concept_id)
        ):
            raise HTTPException(404, detail="Answer attempt not found")
        records = await service.student_mastery(payload.student_id)
        state = next((row for row in records if row.concept_id == payload.concept_id), None)
        if state is None:
            raise HTTPException(
                409,
                detail={
                    "code": "answer_not_marked",
                    "message": "This answer carries no marked learning evidence.",
                },
            )
        receipt = MasteryUpdateResponse.from_result(
            MasteryUpdateResult(state=state, attention_transfer=0, recommended_modality_shift=False)
        )
        receipt.mastery = receipt.mastery.for_student()
        return receipt
    result = await service.update(
        MasteryUpdate(
            student_id=payload.student_id,
            concept_id=payload.concept_id,
            response_correct=payload.response_correct,
            item_text_density=payload.item_text_density,
            related_concept_ids=tuple(payload.related_concept_ids),
        )
    )
    return MasteryUpdateResponse.from_result(result)


@router.get("/student/{student_id}", response_model=list[MasteryStateResponse])
async def student_mastery(
    student_id: UUID,
    principal: PrincipalDependency,
    service: MasteryDependency,
    session: DatabaseSession,
) -> list[MasteryStateResponse]:
    await require_student_access(session, principal, student_id)
    records = await service.student_mastery(student_id)
    responses = [MasteryStateResponse.from_state(record) for record in records]
    return [row.for_student() for row in responses] if principal.role == "student" else responses


@router.get("/class/{class_id}", response_model=list[ConceptMasteryAggregateResponse])
async def class_mastery(
    class_id: UUID,
    principal: PrincipalDependency,
    service: MasteryDependency,
    session: DatabaseSession,
) -> list[ConceptMasteryAggregateResponse]:
    if principal.role not in {"teacher", "senco_admin", "other_admin"}:
        raise HTTPException(403, detail="Staff account required")
    await require_class_access(session, principal, class_id)
    records = await service.class_mastery(class_id)
    return [ConceptMasteryAggregateResponse.from_aggregate(record) for record in records]


@router.get("/school/{school_id}", response_model=list[ConceptMasteryAggregateResponse])
async def school_mastery(
    school_id: UUID,
    principal: PrincipalDependency,
    service: MasteryDependency,
    session: DatabaseSession,
) -> list[ConceptMasteryAggregateResponse]:
    if principal.role not in {"senco_admin", "other_admin"}:
        raise HTTPException(403, detail="School administrator required")
    actor = await require_school_actor(session, principal, roles={"senco_admin", "other_admin"})
    if actor.school_id != school_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    records = await service.school_mastery(school_id)
    return [ConceptMasteryAggregateResponse.from_aggregate(record) for record in records]
