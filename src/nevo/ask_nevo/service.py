import json
from typing import Protocol
from uuid import UUID

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.entities import AiGenerationRequest
from nevo.ai_gateway.service import AiGatewayService
from nevo.ask_nevo.entities import (
    AskNevoContext,
    AskNevoRequest,
    AskNevoResponse,
)
from nevo.domain.ai_gateway.vocabulary import AiService
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory, AskNevoRole


class AskNevoRepository(Protocol):
    async def build_context(
        self,
        *,
        actor_user_id: UUID,
        request: AskNevoRequest,
    ) -> AskNevoContext: ...

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
        result = await self._gateway.generate(
            AiGenerationRequest(
                requester_user_id=actor_user_id,
                student_id=context.student_id_for_gateway,
                service=AiService.NARRATIVE,
                prompt_name=(
                    "ask_nevo.teacher"
                    if request.role is AskNevoRole.TEACHER
                    else "ask_nevo.student"
                ),
                variables={
                    "question": request.question,
                    "context": json.dumps(context.payload, sort_keys=True, default=str),
                },
                max_output_tokens=900,
            )
        )
        answer = result.text
        if not self._compliance.inspect(answer).allowed:
            retry = await self._gateway.generate(
                AiGenerationRequest(
                    requester_user_id=actor_user_id,
                    student_id=context.student_id_for_gateway,
                    service=AiService.NARRATIVE,
                    prompt_name=(
                        "ask_nevo.teacher"
                        if request.role is AskNevoRole.TEACHER
                        else "ask_nevo.student"
                    ),
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
        interaction_id = await self._repository.log_interaction(
            actor_user_id=actor_user_id,
            request=request,
            category=category,
            ai_gateway_call_id=result.call_id,
        )
        return AskNevoResponse(
            answer=answer,
            question_category=category,
            interaction_id=interaction_id,
            ai_gateway_call_id=result.call_id,
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
