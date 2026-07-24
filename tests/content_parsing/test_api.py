from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.content import router
from nevo.auth.entities import AuthPrincipal
from nevo.content_parsing.entities import ParsedLessonSegment, StoredParsedLesson
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.intelligence.vocabulary import (
    ContentModality,
    ContentParseStatus,
    LessonContentType,
)


class FakeContentParsingService(ContentParsingService):
    def __init__(self) -> None:
        self.requests = []

    async def parse(self, *, request, requested_by_user_id):
        self.requests.append((request, requested_by_user_id))
        return StoredParsedLesson(
            lesson_id=uuid4(),
            parse_run_id=uuid4(),
            status=ContentParseStatus.COMPLETED,
            title=request.title,
            segment_count=1,
            review_segment_count=0,
            confirmation_summary="Parsed 1 lesson segment for teacher review.",
            review_notes=(),
            segments=(
                ParsedLessonSegment(
                    segment_key="intro",
                    content_type=LessonContentType.EXPLANATORY_TEXT,
                    sequence_order=1,
                    title="Intro",
                    body="Plants use sunlight.",
                    available_modalities=(
                        ContentModality.TEXT,
                        ContentModality.AUDIO,
                    ),
                    text_variant={"body": "Plants use sunlight."},
                    audio_variant={
                        "script": "Plants use sunlight.",
                        "audioUrl": "",
                        "durationMs": 0,
                        "provider": "tts_provider_tbd",
                    },
                ),
            ),
        )


def client_for() -> tuple[TestClient, FakeContentParsingService, AuthPrincipal]:
    principal = AuthPrincipal(
        user_id=uuid4(),
        role="teacher",
        session_id=uuid4(),
    )
    service = FakeContentParsingService()
    app = FastAPI()
    app.state.content_parsing_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), service, principal


def test_parse_content_endpoint_returns_structured_segments() -> None:
    client, service, principal = client_for()

    response = client.post(
        "/api/content/parse",
        json={
            "title": "Photosynthesis",
            "sourceType": "text",
            "sourceText": "Plants use sunlight.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["segmentCount"] == 1
    assert payload["segments"][0]["availableModalities"] == ["text", "audio"]
    assert payload["segments"][0]["audioVariant"]["provider"] == "tts_provider_tbd"
    assert service.requests[0][0].title == "Photosynthesis"
    assert service.requests[0][1] == principal.user_id
