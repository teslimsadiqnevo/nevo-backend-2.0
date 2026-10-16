from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from nevo.api.lesson_contracts import TextVariant
from nevo.api.response_models import LessonSummaryResponse
from nevo.content_parsing.delivery import validated_delivery
from nevo.content_parsing.descriptions import clean_lesson_description
from nevo.content_parsing.entities import ContentParseRequest, ParsedLesson
from nevo.content_parsing.repositories import SqlAlchemyContentParsingRepository
from nevo.content_parsing.service import (
    _normalize_segment,
    _segment_from_payload,
    _without_contents_pages,
)
from nevo.domain.intelligence.vocabulary import LessonSourceType


@pytest.mark.parametrize(
    "author",
    [
        "Cosmic",
        "formal_specification",
        "person-authored",
        None,
        12,
        {"name": "publisher"},
        ["person"],
    ],
)
def test_generated_aids_have_server_owned_provenance(author):
    segment = _segment_from_payload(
        {
            "body": "A set contains distinct elements.",
            "text_variant": {
                "keyTerms": [{"term": "set", "definition": "A collection.", "authoredBy": author}],
                "equationCallouts": [{"equation": "A = B", "authoredBy": author}],
            },
        },
        sequence_order=1,
    )
    result = validated_delivery(_normalize_segment(segment))
    assert result.text_variant["keyTerms"][0]["authoredBy"] == "nevo"
    assert result.text_variant["equationCallouts"][0]["authoredBy"] == "nevo"


def test_existing_unknown_publisher_metadata_inherits_known_renderer_provenance():
    result = TextVariant.model_validate(
        {
            "body": "A set contains distinct elements.",
            "authoredBy": "nevo",
            "keyTerms": [{"term": "set", "definition": "A collection.", "authoredBy": "Cosmic"}],
            "equationCallouts": [{"equation": "A = B", "authoredBy": "formal_specification"}],
        }
    )
    assert result.key_terms[0].authored_by == "nevo"
    assert result.equation_callouts[0].authored_by == "nevo"


@pytest.mark.asyncio
async def test_unreadable_variants_are_rejected_before_database_access():
    factory = Mock(side_effect=AssertionError("Database must not be opened"))
    segment = _segment_from_payload({"body": "A real teaching paragraph."}, sequence_order=1)
    bad_segment = replace(segment, visual_variant={"kind": "conceptual_diagram"})
    with pytest.raises(ValidationError):
        await SqlAlchemyContentParsingRepository(factory).store(
            request=ContentParseRequest(title="Sets", source_type=LessonSourceType.TEXT),
            parsed=ParsedLesson(title="Sets", segments=(bad_segment,)),
            requested_by_user_id=uuid4(),
        )
    factory.assert_not_called()


def test_description_is_one_line_content_or_empty_never_timing_breakdown():
    timing = "Total: 99 min (Segment 1: 2 min, Segment 2: 1 min)"
    assert clean_lesson_description(timing) is None
    assert clean_lesson_description("Learn sets.\nThen practise schemas.") == (
        "Learn sets. Then practise schemas."
    )
    summary = LessonSummaryResponse(
        id=uuid4(),
        title="Z guide",
        description=timing,
        status="completed",
        sourceType="pdf",
        segmentCount=45,
        reviewSegmentCount=45,
        createdAt=datetime.now(UTC),
    )
    assert summary.description is None


def test_contents_and_continuation_pages_are_not_expanded_into_teaching():
    source = (
        "[Page 1]\nGuide overview\nContents\n"
        "Formal methods . . . . 3\nBenefits . . . . 3\nTypes . . . . 5\n"
        "[Page 2]\nRelations . . . . 9\nOverriding . . . . 10\nSchemas . . . . 11\n"
        "[Page 3]\nWhat formal methods are\nFormal methods use precise mathematical notation."
    )
    result, pages = _without_contents_pages(source)
    assert pages == [1, 2]
    assert result.startswith("[Page 3]")
    assert "Formal methods use precise mathematical notation." in result
    assert "Overriding . . . . 10" not in result
    assert _without_contents_pages("A normal lesson about sets.") == (
        "A normal lesson about sets.",
        [],
    )
