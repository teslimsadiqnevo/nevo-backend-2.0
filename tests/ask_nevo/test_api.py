from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.ask_nevo import router
from nevo.api.auth import authenticated_principal
from nevo.ask_nevo.entities import AskNevoResponse
from nevo.ask_nevo.service import AskNevoService
from nevo.auth.entities import AuthPrincipal
from nevo.domain.ask_nevo.vocabulary import AskNevoQuestionCategory

INTERACTION_ID = UUID("00000000-0000-4000-8000-000000000001")
CALL_ID = UUID("00000000-0000-4000-8000-000000000002")


class FakeAskNevoService(AskNevoService):
    def __init__(self) -> None:
        self.requests = []
        self.helpful = None

    async def ask(self, *, actor_user_id, request):
        self.requests.append((actor_user_id, request))
        return AskNevoResponse(
            answer="Let's use the current example and try one smaller step.",
            question_category=AskNevoQuestionCategory.LESSON_HELP,
            interaction_id=INTERACTION_ID,
            ai_gateway_call_id=CALL_ID,
        )

    async def record_helpfulness(self, *, interaction_id, helpful):
        self.helpful = (interaction_id, helpful)


def client_for() -> tuple[TestClient, FakeAskNevoService, AuthPrincipal]:
    principal = AuthPrincipal(user_id=uuid4(), role="student", session_id=uuid4())
    service = FakeAskNevoService()
    app = FastAPI()
    app.state.ask_nevo_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), service, principal


def test_student_ask_nevo_returns_answer() -> None:
    client, service, principal = client_for()

    response = client.post(
        "/api/v1/ask-nevo/",
        json={
            "role": "student",
            "currentPage": "lesson_player",
            "contextIds": {
                "studentId": str(principal.user_id),
                "lessonId": str(uuid4()),
                "segmentId": "segment-1",
            },
            "question": "Can you explain this?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["question_category"] == "lesson_help"
    assert body["interaction_id"] == str(INTERACTION_ID)
    assert service.requests[0][1].current_page == "lesson_player"


def test_student_ask_nevo_rejects_other_student_context() -> None:
    client, service, _ = client_for()

    response = client.post(
        "/api/v1/ask-nevo/",
        json={
            "role": "student",
            "currentPage": "lesson_player",
            "contextIds": {"studentId": str(uuid4())},
            "question": "Can you explain this?",
        },
    )

    assert response.status_code == 403
    assert service.requests == []


def test_records_helpfulness_signal() -> None:
    client, service, _ = client_for()

    response = client.post(
        f"/api/v1/ask-nevo/{INTERACTION_ID}/helpfulness",
        json={"helpful": True},
    )

    assert response.status_code == 204
    assert service.helpful == (INTERACTION_ID, True)
