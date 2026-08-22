from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.intelligence import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.intelligence.vocabulary import AccommodationType
from nevo.intelligence.accommodation_service import AccommodationInferenceService
from nevo.intelligence.entities import AccommodationAnalysis, AccommodationSignal


class FakeAccommodationInferenceService(AccommodationInferenceService):
    async def analyse_student(self, *, student_id):
        return AccommodationAnalysis(
            student_id=student_id,
            active=(
                AccommodationSignal(
                    accommodation=AccommodationType.READING,
                    frontend_signal="reading_accommodation_active",
                    evidence=(
                        "high_reading_latency_on_text_heavy_segments",
                        "elevated_backward_scroll_regressions",
                        "long_pauses_on_words_or_phrases",
                    ),
                    lesson_count=5,
                ),
            ),
            source="aggregated_behavioural_patterns",
        )


def client_for(*, role="student", user_id=None):
    principal = AuthPrincipal(
        user_id=user_id or uuid4(),
        role=role,
        session_id=uuid4(),
    )
    app = FastAPI()
    app.state.accommodation_inference_service = FakeAccommodationInferenceService(
        repository=None,  # type: ignore[arg-type]
        engine=None,  # type: ignore[arg-type]
    )
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), principal


def test_accommodation_endpoint_returns_current_session_signals() -> None:
    client, principal = client_for()

    response = client.get(f"/api/intelligence/accommodations/{principal.user_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["activeAccommodations"] == ["reading"]
    assert body["frontendSignals"] == ["reading_accommodation_active"]
    assert body["persistedAsLabel"] is False


def test_student_cannot_request_another_students_accommodation_state() -> None:
    client, _ = client_for()

    response = client.get(f"/api/intelligence/accommodations/{uuid4()}")

    assert response.status_code == 403
