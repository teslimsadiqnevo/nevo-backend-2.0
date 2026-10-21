from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.consent import require_learning_consent_if_student
from nevo.api.dependencies import database_session
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


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    async def prepare(session, principal, payload, signals):
        from nevo.api.intelligence import _segment_from_request

        return AdaptationRequest(
            student_id=principal.user_id,
            lesson_id=payload.lesson_id,
            session_id=payload.session_id,
            mode=payload.mode,
            signals=signals,
            segments=tuple(_segment_from_request(item) for item in payload.segments),
        )

    monkeypatch.setattr("nevo.intelligence.adaptation_context.prepare_adaptation", prepare)


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
    from nevo.ai_gateway.safety import POLICY_VERSION

    segment = SimpleNamespace(
        id=uuid4(),
        segment_key="intro",
        body="A lesson.",
        content_type="explanatory_text",
        available_modalities=["visual", "text"],
        visual_variant={"safetyPolicyVersion": POLICY_VERSION, "imageUrl": "https://example.org/a"},
        audio_variant=None,
        calculation_variant=None,
        interactive_variant=None,
    )
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[database_session] = lambda: SimpleNamespace(
        get=AsyncMock(return_value=None), scalar=AsyncMock(return_value=segment), commit=AsyncMock()
    )
    app.dependency_overrides[require_learning_consent_if_student] = lambda: None
    app.include_router(router)
    return TestClient(app), service, principal


def test_adapt_endpoint_returns_adaptation_plan() -> None:
    client, service, principal = client_for()
    lesson_id = uuid4()
    session_id = uuid4()

    response = client.post(
        "/api/intelligence/adapt",
        json={
            "lessonId": str(lesson_id),
            "sessionId": str(session_id),
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
                "currentSegmentElapsedSeconds": 30,
                "secondsSinceLastAdaptation": 20,
                "sessionModalityShiftCount": 2,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["source"] == "rule_based"
    assert response.json()["segments"][0] == {
        "segmentId": "intro",
        "modality": "visual",
        "density": "low",
        "scaffolding": "strong",
        "priority": 80,
        "availableFormats": ["visual", "text"],
        "recommendedFormat": None,
        "chosenDepth": None,
        "slower": None,
    }
    assert service.requests[0].mode is AdaptationMode.IN_LESSON
    assert service.requests[0].student_id == principal.user_id
    assert service.requests[0].session_id == session_id
    assert service.requests[0].signals.current_segment_elapsed_seconds is None
    assert service.requests[0].signals.seconds_since_last_adaptation is None
    assert service.requests[0].signals.session_modality_shift_count is None


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
