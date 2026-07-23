from types import SimpleNamespace
from uuid import UUID

import pytest

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ask_nevo.entities import (
    AskNevoContext,
    AskNevoContextIds,
    AskNevoRequest,
)
from nevo.ask_nevo.service import AskNevoService
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory, AskNevoRole

ACTOR_ID = UUID("00000000-0000-4000-8000-000000000001")
CALL_ID = UUID("00000000-0000-4000-8000-000000000002")
RETRY_CALL_ID = UUID("00000000-0000-4000-8000-000000000003")
INTERACTION_ID = UUID("00000000-0000-4000-8000-000000000004")


class FakeGateway:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        text = self.texts.pop(0)
        call_id = RETRY_CALL_ID if len(self.requests) > 1 else CALL_ID
        return SimpleNamespace(text=text, call_id=call_id)


class FakeRepository:
    def __init__(self) -> None:
        self.logged_question_text = None
        self.category = None
        self.helpful = None

    async def build_context(self, *, actor_user_id, request):
        assert actor_user_id == ACTOR_ID
        return AskNevoContext(
            payload={"current_page": request.current_page, "specific": True},
            student_id_for_gateway=request.context_ids.student_id,
        )

    async def log_interaction(
        self,
        *,
        actor_user_id,
        request,
        category,
        ai_gateway_call_id,
    ):
        assert actor_user_id == ACTOR_ID
        assert ai_gateway_call_id in {CALL_ID, RETRY_CALL_ID}
        self.logged_question_text = None
        self.category = category
        return INTERACTION_ID

    async def record_helpfulness(self, *, interaction_id, helpful):
        assert interaction_id == INTERACTION_ID
        self.helpful = helpful


@pytest.mark.asyncio
async def test_ask_nevo_uses_teacher_prompt_and_logs_category() -> None:
    repository = FakeRepository()
    gateway = FakeGateway("Try a shorter worked example first.")
    service = AskNevoService(
        repository=repository,
        gateway=gateway,  # type: ignore[arg-type]
        compliance=ZeroTagCompliancePolicy(),
    )

    result = await service.ask(
        actor_user_id=ACTOR_ID,
        request=AskNevoRequest(
            role=AskNevoRole.TEACHER,
            current_page="student_profile",
            context_ids=AskNevoContextIds(),
            question="What does Amara's pattern tell me?",
        ),
    )

    assert gateway.requests[0].prompt_name == "ask_nevo.teacher"
    assert result.question_category is AskNevoQuestionCategory.PROFILE_PATTERN
    assert result.interaction_id == INTERACTION_ID
    assert repository.logged_question_text is None


@pytest.mark.asyncio
async def test_ask_nevo_retries_zero_tag_violation() -> None:
    service = AskNevoService(
        repository=FakeRepository(),
        gateway=FakeGateway(
            "This looks like a diagnostic issue.",
            "Use a clearer worked example and a quick check-in.",
        ),  # type: ignore[arg-type]
        compliance=ZeroTagCompliancePolicy(),
    )

    result = await service.ask(
        actor_user_id=ACTOR_ID,
        request=AskNevoRequest(
            role=AskNevoRole.STUDENT,
            current_page="lesson_player",
            context_ids=AskNevoContextIds(),
            question="Can you help me understand this?",
        ),
    )

    assert result.answer == "Use a clearer worked example and a quick check-in."
    assert result.ai_gateway_call_id == RETRY_CALL_ID
