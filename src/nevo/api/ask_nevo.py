from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.ask_nevo.entities import AskNevoContextIds, AskNevoRequest, AskNevoResponse
from nevo.ask_nevo.formatting import AnswerBlockType, AnswerFormat, structure_answer
from nevo.ask_nevo.service import AskNevoService
from nevo.db.models.ask_nevo import AskNevoInteraction
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory, AskNevoRole

router = APIRouter(prefix="/api/v1/ask-nevo", tags=["ask-nevo"])


class ContextIdsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    student_id: UUID | None = Field(default=None, alias="studentId")
    class_id: UUID | None = Field(default=None, alias="classId")
    lesson_id: UUID | None = Field(default=None, alias="lessonId")
    segment_id: str | None = Field(default=None, alias="segmentId", max_length=120)
    thread_id: UUID | None = Field(default=None, alias="threadId")


class AskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: AskNevoRole
    current_page: str = Field(alias="currentPage", min_length=2, max_length=120)
    context_ids: ContextIdsRequest = Field(alias="contextIds")
    question: str = Field(min_length=2, max_length=2_000)


class AnswerBlockResponse(BaseModel):
    """One renderable piece of an answer.

    A client that only handles ``paragraph`` can render ``text`` for every
    block and still be correct, so adopting this is optional.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: AnswerBlockType
    text: str = ""
    items: list[str] = Field(default_factory=list)
    level: int = 0


class AskResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    #: The model's answer exactly as returned, unchanged. Kept so nothing that
    #: already reads it breaks, and so the raw output stays inspectable.
    answer: str
    #: The same answer normalised into blocks. Parsed once here rather than in
    #: each client, so every surface renders identically.
    blocks: list[AnswerBlockResponse] = Field(default_factory=list)
    #: The answer flattened back to prose, markers removed. For clients that
    #: want one string and no block handling.
    plain_text: str = Field(default="", alias="plainText")
    #: Whether the model actually produced structure this time.
    answer_format: AnswerFormat = Field(
        default=AnswerFormat.PLAIN,
        alias="answerFormat",
    )
    question_category: AskNevoQuestionCategory
    interaction_id: UUID
    ai_gateway_call_id: UUID

    @classmethod
    def from_result(cls, result: AskNevoResponse) -> "AskResponse":
        structured = structure_answer(result.answer)
        return cls(
            answer=result.answer,
            blocks=[
                AnswerBlockResponse(
                    type=block.type,
                    text=block.text,
                    items=list(block.items),
                    level=block.level,
                )
                for block in structured.blocks
            ],
            plain_text=structured.plain_text,
            answer_format=structured.format,
            question_category=result.question_category,
            interaction_id=result.interaction_id,
            ai_gateway_call_id=result.ai_gateway_call_id,
        )


class HelpfulnessRequest(BaseModel):
    helpful: bool


def get_ask_nevo_service(request: Request) -> AskNevoService:
    service = getattr(request.app.state, "ask_nevo_service", None)
    if not isinstance(service, AskNevoService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Ask Nevo is temporarily unavailable.",
            },
        )
    return service


AskNevoDependency = Annotated[AskNevoService, Depends(get_ask_nevo_service)]


@router.post("/", response_model=AskResponse)
async def ask_nevo(
    payload: AskRequest,
    principal: PrincipalDependency,
    service: AskNevoDependency,
) -> AskResponse:
    if payload.role is AskNevoRole.STUDENT:
        context_student_id = payload.context_ids.student_id or principal.user_id
        if context_student_id != principal.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "student_context_forbidden",
                    "message": "Student Ask Nevo must use the current student.",
                },
            )
    result = await service.ask(
        actor_user_id=principal.user_id,
        request=AskNevoRequest(
            role=payload.role,
            current_page=payload.current_page,
            context_ids=AskNevoContextIds(
                student_id=payload.context_ids.student_id,
                class_id=payload.context_ids.class_id,
                lesson_id=payload.context_ids.lesson_id,
                segment_id=payload.context_ids.segment_id,
                thread_id=payload.context_ids.thread_id,
            ),
            question=payload.question,
        ),
    )
    return AskResponse.from_result(result)


@router.post("/{interaction_id}/helpfulness", status_code=status.HTTP_204_NO_CONTENT)
async def record_helpfulness(
    interaction_id: UUID,
    payload: HelpfulnessRequest,
    principal: PrincipalDependency,
    service: AskNevoDependency,
    session: DatabaseSession,
) -> None:
    interaction = await session.get(AskNevoInteraction, interaction_id)
    if interaction is None or interaction.actor_user_id != principal.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interaction not found")
    await service.record_helpfulness(
        interaction_id=interaction_id,
        helpful=payload.helpful,
    )
