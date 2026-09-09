import json
from typing import Any, Protocol
from uuid import UUID, uuid4

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.service import AiGatewayService
from nevo.ask_nevo.entities import (
    AskNevoContext,
    AskNevoRequest,
    AskNevoResponse,
    ThreadSummary,
    ThreadTranscript,
)
from nevo.ask_nevo.formatting import structure_answer
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory, AskNevoRole
from nevo.ops.background import spawn


class AskNevoRepository(Protocol):
    async def build_context(
        self,
        *,
        actor_user_id: UUID,
        request: AskNevoRequest,
    ) -> AskNevoContext: ...

    async def build_toolset(
        self,
        *,
        actor_user_id: UUID,
        role: AskNevoRole,
    ) -> tuple[tuple[dict[str, object], ...], object, Any]: ...

    async def log_interaction(
        self,
        *,
        actor_user_id: UUID,
        request: AskNevoRequest,
        category: AskNevoQuestionCategory,
        ai_gateway_call_id: UUID,
    ) -> UUID: ...

    async def record_helpfulness(
        self,
        *,
        interaction_id: UUID,
        helpful: bool,
    ) -> None: ...

    async def append_exchange(
        self,
        *,
        thread_id: UUID,
        actor_user_id: UUID,
        role: AskNevoRole,
        question: str,
        answer: str,
        blocks: list[dict[str, object]],
        interaction_id: UUID | None,
    ) -> None: ...

    async def list_threads(
        self,
        *,
        actor_user_id: UUID,
        limit: int = 50,
    ) -> list[ThreadSummary]: ...

    async def read_thread(
        self,
        *,
        actor_user_id: UUID,
        thread_id: UUID,
    ) -> ThreadTranscript | None: ...

    async def delete_thread(
        self,
        *,
        actor_user_id: UUID,
        thread_id: UUID,
    ) -> bool: ...


class AskNevoService:
    def __init__(
        self,
        *,
        repository: AskNevoRepository,
        gateway: AiGatewayService,
        compliance: ZeroTagCompliancePolicy,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._compliance = compliance

    async def ask(
        self,
        *,
        actor_user_id: UUID,
        request: AskNevoRequest,
    ) -> AskNevoResponse:
        category = classify_question(request.question)
        context = await self._repository.build_context(
            actor_user_id=actor_user_id,
            request=request,
        )
        # Tools let the model reach data the frontend could not have named -
        # a question mentioning a learner the page never identified. The
        # directory is built from this actor's own accessible set, so it also
        # bounds what any tool can reach.
        tools, executor, directory = await self._repository.build_toolset(
            actor_user_id=actor_user_id,
            role=request.role,
        )
        result = await self._gateway.generate(
            AiGenerationRequest(
                requester_user_id=actor_user_id,
                student_id=context.student_id_for_gateway,
                service=AiService.NARRATIVE,
                prompt_name=_prompt_for(request.role),
                variables={
                    "question": request.question,
                    "context": json.dumps(context.payload, sort_keys=True, default=str),
                },
                max_output_tokens=900,
                tools=tools,
                tool_executor=executor,
            )
        )
        answer = result.text
        if not self._compliance.inspect(answer).allowed:
            retry = await self._gateway.generate(
                AiGenerationRequest(
                    requester_user_id=actor_user_id,
                    student_id=context.student_id_for_gateway,
                    service=AiService.NARRATIVE,
                    prompt_name=_prompt_for(request.role),
                    variables={
                        "question": (
                            f"{request.question}\n\nRewrite your answer using only "
                            "observable classroom behavior and functional learning "
                            "support language."
                        ),
                        "context": json.dumps(
                            context.payload,
                            sort_keys=True,
                            default=str,
                        ),
                    },
                    max_output_tokens=900,
                )
            )
            answer = retry.text
            result = retry
        if not self._compliance.inspect(answer).allowed:
            answer = self._compliance.sanitize(answer)
        # Names go back only here, on the way to the user. The model saw
        # pseudonyms throughout, including in every tool result.
        if directory is not None:
            answer = directory.rehydrate(answer)
        interaction_id = await self._repository.log_interaction(
            actor_user_id=actor_user_id,
            request=request,
            category=category,
            ai_gateway_call_id=result.call_id,
        )
        thread_id = request.context_ids.thread_id or uuid4()
        # Written behind the response. The person asking has already waited on
        # a model; two more round trips before they see anything would be
        # latency spent on our own record keeping. The cost is that a crash
        # between answering and writing loses that one exchange.
        spawn(
            lambda: self._repository.append_exchange(
                thread_id=thread_id,
                actor_user_id=actor_user_id,
                role=request.role,
                question=request.question,
                answer=answer,
                blocks=blocks_for(answer),
                interaction_id=interaction_id,
            ),
            name=f"ask-nevo-thread-{thread_id}",
        )
        return AskNevoResponse(
            answer=answer,
            question_category=category,
            interaction_id=interaction_id,
            ai_gateway_call_id=result.call_id,
            thread_id=thread_id,
        )

    async def list_threads(self, *, actor_user_id: UUID) -> list[ThreadSummary]:
        return await self._repository.list_threads(actor_user_id=actor_user_id)

    async def read_thread(
        self,
        *,
        actor_user_id: UUID,
        thread_id: UUID,
    ) -> ThreadTranscript | None:
        return await self._repository.read_thread(
            actor_user_id=actor_user_id,
            thread_id=thread_id,
        )

    async def delete_thread(
        self,
        *,
        actor_user_id: UUID,
        thread_id: UUID,
    ) -> bool:
        return await self._repository.delete_thread(
            actor_user_id=actor_user_id,
            thread_id=thread_id,
        )

    async def record_helpfulness(
        self,
        *,
        interaction_id: UUID,
        helpful: bool,
    ) -> None:
        await self._repository.record_helpfulness(
            interaction_id=interaction_id,
            helpful=helpful,
        )


def classify_question(question: str) -> AskNevoQuestionCategory:
    text = question.casefold()
    if any(word in text for word in ("parent", "message", "guardian")):
        return AskNevoQuestionCategory.FAMILY_MESSAGE
    if any(word in text for word in ("flag", "prioritise", "prioritize")):
        return AskNevoQuestionCategory.FLAG_REVIEW
    if any(word in text for word in ("class", "lesson would work", "struggling")):
        return AskNevoQuestionCategory.CLASS_PLANNING
    if any(word in text for word in ("pattern", "learns", "slower")):
        return AskNevoQuestionCategory.PROFILE_PATTERN
    if any(word in text for word in ("explain", "help", "understand")):
        return AskNevoQuestionCategory.LESSON_HELP
    return AskNevoQuestionCategory.GENERAL


def _prompt_for(role: AskNevoRole) -> str:
    """Which voice answers.

    An administrator gets the teacher's voice - the questions are the same
    shape - but a wider toolset. A parent has their own, because the thing
    they must never be handed is a number about their child.
    """
    if role is AskNevoRole.STUDENT:
        return "ask_nevo.student"
    if role is AskNevoRole.PARENT:
        return "ask_nevo.parent"
    return "ask_nevo.teacher"


def blocks_for(answer: str) -> list[dict[str, object]]:
    """The rendered shape, stored beside the text.

    Kept so reopening a chat shows what was shown, rather than a fresh
    derivation that may have drifted as the formatter changes.
    """
    structured = structure_answer(answer)
    return [
        {"type": block.type.value, "text": block.text, "items": list(block.items)}
        for block in structured.blocks
    ]
