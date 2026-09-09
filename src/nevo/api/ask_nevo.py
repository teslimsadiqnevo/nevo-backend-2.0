from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from nevo.api.auth import PrincipalDependency
from nevo.api.dependencies import DatabaseSession
from nevo.ask_nevo.entities import (
    AskNevoContextIds,
    AskNevoRequest,
    AskNevoResponse,
    ThreadSummary,
    ThreadTranscript,
)
from nevo.ask_nevo.formatting import AnswerBlockType, AnswerFormat, structure_answer
from nevo.ask_nevo.service import AskNevoService
from nevo.db.models.ask_nevo import AskNevoInteraction
from nevo.domain.ask_nevo.vocabulary import (
    AskNevoMessageAuthor,
    AskNevoQuestionCategory,
    AskNevoRole,
)

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
    #: The conversation this answer belongs to. Send it back as
    #: contextIds.threadId on the next question to continue the same chat.
    thread_id: UUID | None = Field(default=None, alias="threadId")

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
            thread_id=result.thread_id,
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


#: Which asking roles each signed-in role may use. An administrator may ask as
#: a teacher too, because a SENCO reading one class is doing a teacher's job.
_ROLES_FOR_PRINCIPAL: dict[str, tuple[AskNevoRole, ...]] = {
    "student": (AskNevoRole.STUDENT,),
    "teacher": (AskNevoRole.TEACHER,),
    "parent_guardian": (AskNevoRole.PARENT,),
    "senco_admin": (AskNevoRole.ADMIN, AskNevoRole.TEACHER),
    "other_admin": (AskNevoRole.ADMIN, AskNevoRole.TEACHER),
}


@router.post("/", response_model=AskResponse)
async def ask_nevo(
    payload: AskRequest,
    principal: PrincipalDependency,
    service: AskNevoDependency,
) -> AskResponse:
    # The asking role decides both the voice and the tools, so it cannot be
    # whatever the client sends. A learner claiming to be a teacher would
    # otherwise be offered the roster.
    if payload.role not in _ROLES_FOR_PRINCIPAL.get(principal.role, ()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ask_role_forbidden",
                "message": "You cannot ask Nevo in that role.",
            },
        )
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


class ThreadSummaryResponse(BaseModel):
    """One past conversation, as a list of them shows it."""

    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")
    title: str
    role: AskNevoRole
    message_count: int = Field(alias="messageCount")
    last_message_at: datetime = Field(alias="lastMessageAt")
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_summary(cls, summary: ThreadSummary) -> "ThreadSummaryResponse":
        return cls(
            threadId=summary.thread_id,
            title=summary.title,
            role=summary.role,
            messageCount=summary.message_count,
            lastMessageAt=summary.last_message_at,
            createdAt=summary.created_at,
        )


class ThreadMessageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: UUID = Field(alias="messageId")
    author: AskNevoMessageAuthor
    sequence: int
    text: str
    #: The blocks as they were rendered at the time, so reopening a chat shows
    #: what was shown.
    blocks: list[AnswerBlockResponse]
    created_at: datetime = Field(alias="createdAt")


class ThreadTranscriptResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")
    title: str
    role: AskNevoRole
    created_at: datetime = Field(alias="createdAt")
    messages: list[ThreadMessageResponse]

    @classmethod
    def from_transcript(cls, transcript: ThreadTranscript) -> "ThreadTranscriptResponse":
        return cls(
            threadId=transcript.thread_id,
            title=transcript.title,
            role=transcript.role,
            createdAt=transcript.created_at,
            messages=[
                ThreadMessageResponse(
                    messageId=item.message_id,
                    author=item.author,
                    sequence=item.sequence,
                    text=item.body,
                    blocks=[
                        AnswerBlockResponse(
                            type=AnswerBlockType(block.get("type") or "paragraph"),
                            text=str(block.get("text") or ""),
                            items=[str(entry) for entry in (block.get("items") or [])],
                        )
                        for block in item.blocks
                    ],
                    createdAt=item.created_at,
                )
                for item in transcript.messages
            ],
        )


@router.get("/threads", response_model=list[ThreadSummaryResponse])
async def list_threads(
    principal: PrincipalDependency,
    service: AskNevoDependency,
) -> list[ThreadSummaryResponse]:
    """This asker's own past conversations, most recent first."""
    return [
        ThreadSummaryResponse.from_summary(item)
        for item in await service.list_threads(actor_user_id=principal.user_id)
    ]


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadTranscriptResponse,
    responses={404: {"description": "No such conversation for this user"}},
)
async def read_thread(
    thread_id: UUID,
    principal: PrincipalDependency,
    service: AskNevoDependency,
) -> ThreadTranscriptResponse:
    """One conversation, in order, ready to render.

    Scoped to the person who had it. A learner's questions are not a
    staffroom read, so a teacher resolving this gets a 404 like anyone else.
    """
    transcript = await service.read_thread(
        actor_user_id=principal.user_id,
        thread_id=thread_id,
    )
    if transcript is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "thread_not_found", "message": "No such conversation."},
        )
    return ThreadTranscriptResponse.from_transcript(transcript)


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: UUID,
    principal: PrincipalDependency,
    service: AskNevoDependency,
) -> None:
    """Let someone throw away a conversation they had."""
    if not await service.delete_thread(
        actor_user_id=principal.user_id,
        thread_id=thread_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "thread_not_found", "message": "No such conversation."},
        )


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
