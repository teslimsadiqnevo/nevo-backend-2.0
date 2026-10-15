import asyncio
import json
from uuid import uuid4

import pytest

from nevo.api.lesson_contracts import EquationCallout
from nevo.api.response_models import LessonSegmentResponse
from nevo.content_parsing.entities import ContentParseRequest
from nevo.content_parsing.service import (
    MAX_CHUNK_CHARS,
    ContentParsingService,
    _segment_from_payload,
)
from nevo.domain.intelligence.vocabulary import LessonSourceType

from .test_service import FakeGateway, FakeRepository


def test_invalid_image_proposal_and_authorship_alias_do_not_break_read():
    response = LessonSegmentResponse(
        id=uuid4(),
        segmentKey="notation",
        sequenceOrder=1,
        contentType="explanatory_text",
        title="Notation",
        body="Z describes a system.",
        availableModalities=["text"],
        comprehensionCheckpoints=[],
        visualVariant={"kind": "conceptual_diagram"},
        textVariant={
            "body": "Z describes a system.",
            "equationCallouts": [{"equation": "x = y", "authoredBy": "person-authored"}],
        },
    )
    assert response.visual_variant is None
    assert response.text_variant.equation_callouts[0].authored_by == "person"
    assert EquationCallout(equation="x = y", authoredBy="nevo-authored").authored_by == "nevo"
    segment = _segment_from_payload(
        {
            "body": "Notation",
            "text_variant": {
                "equationCallouts": [{"equation": "x = y", "authoredBy": "person-authored"}]
            },
        },
        sequence_order=1,
    )
    assert segment.text_variant["equationCallouts"][0]["authoredBy"] == "person"


@pytest.mark.asyncio
async def test_passes_overlap_with_context_and_wrapups_are_only_at_the_end():
    class Gateway(FakeGateway):
        active = 0
        peak = 0

        async def generate(self, request):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            index = request.variables["chunk_number"]
            self.text = json.dumps(
                {
                    "segments": [
                        {
                            "segment_key": "topic",
                            "title": f"Topic {index}",
                            "body": f"Distinct teaching content {index}",
                            "availableModalities": ["text"],
                        },
                        {
                            "segment_key": "closing",
                            "title": "Lesson Recap",
                            "body": f"Closing observation {index}",
                            "availableModalities": ["text"],
                        },
                    ]
                }
            )
            result = await super().generate(request)
            self.active -= 1
            return result

    gateway = Gateway("")
    repository = FakeRepository()
    await ContentParsingService(repository=repository, ai_gateway=gateway).parse(
        request=ContentParseRequest(
            title="Long guide",
            source_type=LessonSourceType.TEXT,
            source_text="Some source material. " * 1000,
        ),
        requested_by_user_id=uuid4(),
    )
    assert gateway.peak == 2
    assert len(gateway.requests) > 2
    assert all(
        len(request.variables["source_text"]) <= MAX_CHUNK_CHARS for request in gateway.requests
    )
    assert "PREVIOUS CONTEXT ONLY" in gateway.requests[1].variables["source_text"]
    parsed = repository.parsed
    assert all(segment.title != "Lesson Recap" for segment in parsed.segments)
    assert "Closing observation 1" in parsed.recap
    assert len({segment.segment_key for segment in parsed.segments}) == len(parsed.segments)
