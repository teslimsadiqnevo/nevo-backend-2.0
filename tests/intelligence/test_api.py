from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.intelligence import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.intelligence.vocabulary import (
    AdaptationMode,
    ContentModality,
    DensityLevel,
    ScaffoldingLevel,
)
from nevo.intelligence.adaptation import AdaptationEngineService
from nevo.intelligence.entities import (
    AdaptationPlan,
    AdaptationRequest,
    BreakThresholdResult,
    SegmentAdaptation,
)


class FakeAdaptationEngineService(AdaptationEngineService):
    def __init__(self) -> None:
        self.requests: list[AdaptationRequest] = []

    async def adapt(
        self,
        *,
        request: AdaptationRequest,
        requested_by_user_id,
    ) -> AdaptationPlan:
        self.requests.append(request)
        return AdaptationPlan(
            lesson_id=request.lesson_id,
            segments=(
                SegmentAdaptation(
                    segment_id=request.segments[0].id,
                    modality=ContentModality.VISUAL,
                    density=DensityLevel.LOW,
                    scaffolding=ScaffoldingLevel.STRONG,
                    priority=80,
                ),
            ),
            break_suggestion=BreakThresholdResult(
                triggered_thresholds=("time_threshold",),
                severity="mild",
                break_type=None,
                reason="test",
            ),
            proactive_adjustment=None,
            modality_suggestion=None,
            source="rule_based",
        )


def client_for() -> tuple[TestClient, FakeAdaptationEngineService, AuthPrincipal]:
    principal = AuthPrincipal(
        user_id=uuid4(),
        role="student",
        session_id=uuid4(),
    )
    service = FakeAdaptationEngineService()
    app = FastAPI()
    app.state.adaptation_engine_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), service, principal


def test_adapt_endpoint_returns_adaptation_plan() -> None:
    client, service, principal = client_for()
    lesson_id = uuid4()

    response = client.post(
        "/api/intelligence/adapt",
        json={
            "lessonId": str(lesson_id),
            "mode": "in_lesson",
            "segments": [
                {
                    "id": "intro",
                    "segmentType": "diagram",
                    "availableModalities": ["visual", "text"],
                }
            ],
            "signals": {
                "continuousMinutes": 21,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["source"] == "rule_based"
    assert response.json()["segments"][0] == {
        "segment_id": "intro",
        "modality": "visual",
        "density": "low",
        "scaffolding": "strong",
        "priority": 80,
    }
    assert service.requests[0].mode is AdaptationMode.IN_LESSON
    assert service.requests[0].student_id == principal.user_id


def test_adapt_endpoint_rejects_different_student_context() -> None:
    client, service, _ = client_for()

    response = client.post(
        "/api/intelligence/adapt",
        json={
            "studentId": str(uuid4()),
            "lessonId": str(uuid4()),
            "segments": [
                {
                    "id": "intro",
                    "segmentType": "diagram",
                    "availableModalities": ["visual", "text"],
                }
            ],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "student_context_forbidden"
    assert service.requests == []
