from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.mastery.entities import (
    ConceptMasteryAggregate,
    MasteryState,
    MasteryUpdate,
    MasteryUpdateResult,
)
from nevo.mastery.service import MasteryService

router = APIRouter(prefix="/api/mastery", tags=["mastery"])


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


class MasteryStateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID = Field(alias="studentId")
    concept_id: UUID = Field(alias="conceptId")
    mastery_probability_concept: float = Field(alias="masteryProbabilityConcept")
    mastery_probability_reading: float = Field(alias="masteryProbabilityReading")
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
                key: round(value, 6)
                for key, value in state.attention_weights.items()
            },
            practice_count=state.practice_count,
            last_response_correct=state.last_response_correct,
            last_failure_attribution=state.last_failure_attribution,
            seeding_source=state.seeding_source,
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
) -> MasteryUpdateResponse:
    if principal.role == "student" and payload.student_id != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Students can update only their own mastery state.",
            },
        )
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
) -> list[MasteryStateResponse]:
    if principal.role == "student" and student_id != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "student_context_forbidden",
                "message": "Students can view only their own mastery state.",
            },
        )
    records = await service.student_mastery(student_id)
    return [MasteryStateResponse.from_state(record) for record in records]


@router.get("/class/{class_id}", response_model=list[ConceptMasteryAggregateResponse])
async def class_mastery(
    class_id: UUID,
    principal: PrincipalDependency,
    service: MasteryDependency,
) -> list[ConceptMasteryAggregateResponse]:
    del principal
    records = await service.class_mastery(class_id)
    return [
        ConceptMasteryAggregateResponse.from_aggregate(record)
        for record in records
    ]


@router.get("/school/{school_id}", response_model=list[ConceptMasteryAggregateResponse])
async def school_mastery(
    school_id: UUID,
    principal: PrincipalDependency,
    service: MasteryDependency,
) -> list[ConceptMasteryAggregateResponse]:
    del principal
    records = await service.school_mastery(school_id)
    return [
        ConceptMasteryAggregateResponse.from_aggregate(record)
        for record in records
    ]
